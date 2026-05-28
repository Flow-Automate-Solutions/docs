# EC2 internal docs preview

Pipeline that runs `mint dev` for [internal/](../internal) on a long-running EC2 instance, redeployed on every push to `main`.

Workflow: [.github/workflows/deploy-internal-preview.yml](../.github/workflows/deploy-internal-preview.yml).

## Required GitHub Secrets

Set these under **Settings → Secrets and variables → Actions**:

| Secret | Value |
|---|---|
| `EC2_HOST` | DNS or IP of the EC2 instance |
| `EC2_USER` | Login user — `ubuntu` (Ubuntu AMI) or `ec2-user` (Amazon Linux) |
| `EC2_SSH_PRIVATE_KEY` | Private key (full PEM, including header/footer) whose public half is in `~$EC2_USER/.ssh/authorized_keys` on the host |

## One-time EC2 prerequisites

The pipeline installs Node 20, Python 3.13, and the `mint` CLI on first run, but the instance itself must already exist with:

1. **OS:** Ubuntu 22.04+ or Amazon Linux 2023.
2. **Sudo without password** for the SSH user (`%sudo NOPASSWD: ALL` or equivalent) — bootstrap and systemd steps need it.
3. **Security group inbound rules:**
   - TCP 22 from the GitHub Actions runner IP range (or a bastion / fixed jump host).
   - TCP 3000 from whatever range the team uses to view the preview (VPN CIDR, office IP, etc.). **Do not open 3000 to `0.0.0.0/0`** — the docs are internal and `mint dev` has no auth layer.
4. **Outbound internet** for package installs (apt/dnf, NodeSource, npm registry).

## How the deploy works

On push to `main` (touching `internal/`, `_shared/`, `tools/`, or `deploy/ec2/`):

1. Runner SSHes in and `rsync`s the repo to `/opt/magic-cms-docs`.
2. [bootstrap.sh](ec2/bootstrap.sh) installs/refreshes Node, Python, mint (idempotent — fast no-op after the first run).
3. [deploy.sh](ec2/deploy.sh) regenerates `internal/openapi.json`, refreshes the systemd unit if it changed, and restarts the service.
4. Health check: `curl http://127.0.0.1:3000` from the host.

## Operating the service

```bash
sudo systemctl status mint-internal     # check state
sudo journalctl -u mint-internal -f     # tail logs
sudo systemctl restart mint-internal    # force restart
```

The unit lives at `/etc/systemd/system/mint-internal.service`; it's regenerated from [ec2/mint-internal.service](ec2/mint-internal.service) on every deploy, so edit the template in the repo, not the installed copy.

## Out of scope

- **TLS / public exposure.** The service binds plain HTTP on 3000. Putting nginx + Let's Encrypt or an ALB in front is a separate task.
- **External docs.** This pipeline only deploys the internal site. Add a sibling workflow if external needs the same treatment.
- **Instance provisioning.** Terraform/CloudFormation for the EC2 itself isn't wired up here.
