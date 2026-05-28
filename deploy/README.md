# EC2 internal docs preview

Pipeline that runs `mint dev` for [internal/](../internal) on a long-running EC2 instance, redeployed on every push to `main`. Transport is **AWS SSM** (no SSH ingress) authenticated via **GitHub OIDC**.

Workflow: [.github/workflows/deploy-internal-preview.yml](../.github/workflows/deploy-internal-preview.yml).

## Required GitHub Secrets

Set these under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | `arn:aws:iam::<account>:role/<role>` — the IAM role this workflow assumes via OIDC |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_S3_BUCKET` | Bucket name used to ship the repo to the host (artifact transfer only — no public content) |
| `EC2_INSTANCE_ID` | `i-0123456789abcdef0` |
| `EC2_DEPLOY_USER` | Linux user that owns `/opt/magic-cms-docs` and runs `mint dev` — typically `ec2-user` (Amazon Linux) or `ubuntu` (Ubuntu AMI) |

## One-time AWS setup

### 1. GitHub OIDC provider in AWS

If you've never wired GitHub OIDC to this AWS account:

1. IAM → Identity providers → Add provider
2. Provider type: OpenID Connect
3. Provider URL: `https://token.actions.githubusercontent.com`
4. Audience: `sts.amazonaws.com`

### 2. IAM role for the workflow

Create a role (e.g. `magic-cms-docs-deployer`) with this trust policy (scoped to this repo and `main`):

```json
{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": { "Federated": "arn:aws:iam::<account>:oidc-provider/token.actions.githubusercontent.com" },
    "Action": "sts:AssumeRoleWithWebIdentity",
    "Condition": {
      "StringEquals": { "token.actions.githubusercontent.com:aud": "sts.amazonaws.com" },
      "StringLike":   { "token.actions.githubusercontent.com:sub": "repo:Flow-Automate-Solutions/magic-cms-docs:ref:refs/heads/main" }
    }
  }]
}
```

Attach a permissions policy granting:

- `s3:PutObject`, `s3:DeleteObject`, `s3:ListBucket`, `s3:GetObject` on `arn:aws:s3:::<bucket>` and `arn:aws:s3:::<bucket>/magic-cms-docs/internal-preview/*`
- `ssm:SendCommand` on `arn:aws:ec2:<region>:<account>:instance/<instance-id>` and the `AWS-RunShellScript` document
- `ssm:GetCommandInvocation`, `ssm:ListCommandInvocations` on `*`

### 3. EC2 instance prerequisites

The instance itself must:

1. Run Ubuntu 22.04+ or Amazon Linux 2023.
2. Have the **SSM Agent** installed and running (default on those AMIs).
3. Have an **instance profile** with:
   - `AmazonSSMManagedInstanceCore` (lets SSM talk to it)
   - A custom inline policy granting `s3:GetObject`, `s3:ListBucket` on the artifact bucket/prefix (lets the host pull code)
4. Have outbound 443 to `ssm.<region>.amazonaws.com`, `ssmmessages.<region>.amazonaws.com`, `ec2messages.<region>.amazonaws.com`, and S3 (via gateway endpoint or NAT).
5. **No inbound SSH required.** The only inbound rule needed is TCP 3000 from whoever views the preview (VPN CIDR, office IP, etc.). **Do not open 3000 to `0.0.0.0/0`** — `mint dev` has no auth layer.

## How the deploy works

On push to `main` (touching `internal/`, `_shared/`, `tools/`, or `deploy/ec2/`):

1. Runner assumes the IAM role via OIDC.
2. `aws s3 sync` uploads the repo to `s3://<bucket>/magic-cms-docs/internal-preview/`.
3. `aws ssm send-command` runs a single shell payload on the EC2 that:
   - `aws s3 sync`s the repo down to `/opt/magic-cms-docs`
   - runs [bootstrap.sh](ec2/bootstrap.sh) (idempotent install of Node 20, Python 3.13, `mint`)
   - runs [deploy.sh](ec2/deploy.sh) (regenerate openapi, refresh systemd unit, restart service)
   - curls `http://127.0.0.1:3000` to confirm the service is up
4. Workflow polls SSM until terminal status; stdout/stderr from the EC2 are echoed into the Actions log.

## Operating the service

```bash
# From the EC2 (via SSM Session Manager: aws ssm start-session --target <instance-id>)
sudo systemctl status mint-internal
sudo journalctl -u mint-internal -f
sudo systemctl restart mint-internal
```

The unit at `/etc/systemd/system/mint-internal.service` is regenerated from [ec2/mint-internal.service](ec2/mint-internal.service) on every deploy — edit the template in the repo, not the installed copy.

## Out of scope

- **TLS / public exposure.** The service binds plain HTTP on 3000. Put nginx + Let's Encrypt or an ALB in front separately.
- **External docs.** This pipeline only deploys the internal site.
- **Instance provisioning.** The EC2, instance profile, and S3 bucket are assumed to exist.
