# EC2 internal docs preview

Pipeline that runs `mint dev` for [internal/](../internal) on a long-running EC2 instance, fronted by **nginx + HTTP Basic Auth**, with **TLS terminated at Cloudflare**. Redeployed on every push to `main`. Transport between GitHub Actions and the host is **AWS SSM** (no SSH ingress) authenticated via **GitHub OIDC**.

Workflow: [.github/workflows/deploy-internal-preview.yml](../.github/workflows/deploy-internal-preview.yml).

## Required GitHub Secrets

Set these under **Settings → Secrets and variables → Actions → Secrets**:

| Secret | Value |
|---|---|
| `AWS_ROLE_ARN` | IAM role assumed via OIDC |
| `AWS_REGION` | e.g. `us-east-1` |
| `AWS_S3_BUCKET` | Bucket used to ship the repo to the host (artifact transfer only) |
| `EC2_INSTANCE_ID` | `i-0123456789abcdef0` |
| `EC2_DEPLOY_USER` | Linux user that owns `/opt/magic-cms-docs` — typically `ubuntu` or `ec2-user` |
| `PREVIEW_DOMAIN` | DNS name proxied through Cloudflare to the EC2, e.g. `internal-docs-preview.magic-cms.com` |
| `PREVIEW_BASIC_AUTH_USER` | Shared username (e.g. `team`) |
| `PREVIEW_BASIC_AUTH_PASSWORD` | Shared password (cleartext; hashed with bcrypt on the host before writing to disk) |

## One-time setup

### 1. DNS + Cloudflare proxy

1. Create an `A` record for `PREVIEW_DOMAIN` pointing at the EC2's public IPv4 address.
2. **Enable the Cloudflare proxy** (orange cloud) on that record.
3. In Cloudflare → SSL/TLS → Overview, set the encryption mode to **Flexible** (browser→Cloudflare HTTPS, Cloudflare→origin HTTP). Cloudflare's Universal SSL handles the public cert automatically.
4. Optional but recommended: Cloudflare → SSL/TLS → Edge Certificates → enable **Always Use HTTPS** so any plain-HTTP visitor is redirected to HTTPS at the edge.

### 2. Security group

Inbound rules on the EC2:

- TCP **80** from **Cloudflare's IPv4 ranges** (<https://www.cloudflare.com/ips-v4>). This prevents anyone who learns the origin IP from bypassing Cloudflare. The list rarely changes; copy/paste the CIDRs.
- **Remove** any prior TCP 3000 / TCP 443 / TCP 22 rules — they are no longer needed.

Outbound: 443 to AWS endpoints (SSM, S3) and the public internet (apt/dnf, NodeSource, npm).

### 3. AWS — OIDC + IAM role + instance profile

See the earlier setup if not already done:

- GitHub OIDC provider in IAM (audience `sts.amazonaws.com`).
- IAM role trusted by `repo:Flow-Automate-Solutions/magic-cms-docs:ref:refs/heads/main`, with permissions:
  - S3 read/write on `arn:aws:s3:::<bucket>/magic-cms-docs/internal-preview/*`
  - `ssm:SendCommand`, `ssm:GetCommandInvocation` on the instance
- EC2 instance profile with `AmazonSSMManagedInstanceCore` + S3 read on the artifact bucket.

## How the deploy works

On push to `main` (paths: `internal/`, `_shared/`, `tools/`, `deploy/ec2/`):

1. Runner assumes the IAM role via OIDC, `aws s3 sync`s the repo to S3.
2. `aws ssm send-command` runs a single payload on the EC2 that:
   - Ensures AWS CLI v2 is installed.
   - Syncs the repo down to `/opt/magic-cms-docs`.
   - Runs [bootstrap.sh](ec2/bootstrap.sh) — installs Node 20, Python 3.13, `mint`, nginx (idempotent).
   - Runs [deploy.sh](ec2/deploy.sh) — regenerates `internal/openapi.json`, refreshes the systemd unit + htpasswd + nginx vhost, reloads nginx.
   - Health-checks `http://127.0.0.1:3000` (mint dev) and `http://127.0.0.1/` via nginx with `Host: $PREVIEW_DOMAIN` (expect 401 without creds, 200 with). Local check — doesn't depend on Cloudflare.
3. Workflow polls SSM until terminal status and echoes stdout/stderr into the Actions log.

## Viewing the preview

Open `https://<PREVIEW_DOMAIN>/` in a browser, enter the shared `PREVIEW_BASIC_AUTH_USER` + `PREVIEW_BASIC_AUTH_PASSWORD`.

Quick smoke test from a shell:

```bash
curl -I "https://$PREVIEW_DOMAIN/"                          # → 401
curl -I -u "$USER:$PASS" "https://$PREVIEW_DOMAIN/"         # → 200
```

## Operating the host

Connect via SSM Session Manager (no SSH key needed):

```bash
aws ssm start-session --target <EC2_INSTANCE_ID> --region <AWS_REGION>
```

Then on the host:

```bash
sudo systemctl status mint-internal       # mint dev
sudo journalctl -u mint-internal -f
sudo systemctl status nginx
sudo nginx -t                             # validate config
```

The unit template, nginx config, and htpasswd hash are all regenerated from the repo on each deploy — edit the files under [deploy/ec2/](ec2/), not the installed copies.

## Rotating the basic-auth password

Update `PREVIEW_BASIC_AUTH_PASSWORD` in GitHub Secrets, then re-run the workflow (or push any change touching `deploy/ec2/`). The htpasswd file is regenerated and nginx reloaded — no downtime.

## Out of scope

- **SSO / per-user auth.** This setup is a single shared password. For per-user SSO, swap nginx Basic Auth for `oauth2-proxy` in front of mint dev.
- **External docs.** This pipeline only deploys the internal site.
- **Instance provisioning.** EC2, instance profile, S3 bucket, DNS record are assumed to exist.
