# SpareAI — AWS infrastructure

Terraform for the two-instance AWS test environment. Everything else runs locally on the Windows laptop first; AWS is used to prove real cross-host dispatching.

## What this creates

- Region: **eu-central-1** (Frankfurt)
- 2× EC2 **c7i.xlarge** (4 vCPU, 8 GB RAM), Ubuntu 22.04 LTS, 20 GB gp3 root
  - `spareai-a` — intended role: Dispatcher + Agent A + Ollama
  - `spareai-b` — intended role: Agent B + Ollama
- 1× security group:
  - SSH (22) and Dispatcher (8080) ingress from **your laptop's public IP only**
  - Agent port (8081) ingress only from the other instance (SG self-reference) — Agents are not reachable from the internet
- 1× generated SSH keypair, private key written to `infra/spareai-key.pem` (chmod 400)
- `user_data` installs Python 3.11, Ollama, and runs `ollama pull qwen2.5:3b-instruct-q4_K_M` on first boot

Everything else (default VPC and subnet) is reused — no VPC/NAT/EIP charges.

## Cost

Roughly **$0.216/hr × 2 = $0.43/hr** on-demand in Frankfurt, so **~$10/day** while both instances are running. **Stop or destroy when not demoing.** EBS volumes cost ~$0.08/GB/month even when stopped (negligible for 2×20 GB).

## One-time setup on your Windows laptop

### 1. Install tooling

```powershell
winget install --id Hashicorp.Terraform
winget install --id Amazon.AWSCLI
```

Verify:

```powershell
terraform -version
aws --version
```

### 2. Create AWS credentials

1. Sign in to the AWS console → **IAM** → **Users** → **Create user**.
2. User name: `spareai-terraform`. Do **not** give it console access.
3. Attach policy directly: **`AmazonEC2FullAccess`** (sufficient for this PoC; tighten later if desired).
4. Finish, then open the user → **Security credentials** → **Create access key** → **Command Line Interface (CLI)** → create.
5. Copy the Access key ID and Secret access key immediately (shown once).

Configure the AWS CLI:

```powershell
aws configure
# AWS Access Key ID:     <paste>
# AWS Secret Access Key: <paste>
# Default region name:   eu-central-1
# Default output format: json
```

Sanity check:

```powershell
aws sts get-caller-identity
```

## Provisioning

### 1. Get your laptop's current public IP

```powershell
curl ifconfig.me
```

### 2. Apply

From the repo root:

```powershell
cd infra
terraform init
terraform apply -var="my_ip=<paste-ip-from-step-1>"
```

Review the plan, type `yes`. Takes ~2 minutes. First-boot `user_data` (Python + Ollama + model pull) runs for a further 3–5 minutes after SSH is reachable.

### 3. Connect

Outputs include ready-to-paste commands:

```powershell
terraform output
# ssh_a           = "ssh -i infra/spareai-key.pem ubuntu@<ip>"
# ssh_b           = "ssh -i infra/spareai-key.pem ubuntu@<ip>"
# dispatcher_url  = "http://<ip>:8080/"
```

To confirm `user_data` finished on a host:

```bash
ssh -i infra/spareai-key.pem ubuntu@<ip> "ls -l /var/log/spareai-provisioned.marker && ollama list"
```

You should see the marker file and `qwen2.5:3b-instruct-q4_K_M` in `ollama list`.

### 4. Deploy the SpareAI code

Once Prompts 2–4 have produced the Agent and Dispatcher, from the repo root:

```powershell
# Copy code to both instances
scp -i infra/spareai-key.pem -r agent dispatcher requirements.txt ubuntu@<ip-a>:~/spareai/
scp -i infra/spareai-key.pem -r agent         requirements.txt ubuntu@<ip-b>:~/spareai/
```

Then SSH into each, create a venv, `pip install -r requirements.txt`, set env vars (`AGENT_TOKEN`, `CLIENT_TOKEN`, Agent URLs using the **private IPs** from Terraform outputs), and start the processes.

Point the Dispatcher at Agents using **private IPs** (`http://<private-ip-b>:8081`), not public — port 8081 is only open within the security group.

## Tearing down

**Always do this when you're done for the day.**

```powershell
cd infra
terraform destroy -var="my_ip=<your-current-ip>"
```

If you just want to pause (preserve disks + model, resume quickly):

```powershell
aws ec2 stop-instances --instance-ids $(terraform output -json | ConvertFrom-Json | % { $_.instance_a_public_ip }) ...
```

Simpler: use the AWS console → EC2 → select both `spareai-*` instances → **Stop**. Resume with **Start**. Public IPs change on each restart, so re-check `terraform refresh` and `terraform output` after starting.

## Common issues

- **"UnauthorizedOperation" on apply**: the IAM user lacks EC2 permissions. Add `AmazonEC2FullAccess`.
- **IP changed, SSH times out**: re-apply with the new IP: `terraform apply -var="my_ip=<new-ip>"`. Terraform will update only the SG rule.
- **Ollama model missing on first SSH**: `user_data` still running. Wait 2–3 more minutes, re-check `/var/log/spareai-provisioned.marker`.
- **Dispatcher can't reach Agent B**: use the **private** IP of B. Port 8081 is not open to the internet by design.
