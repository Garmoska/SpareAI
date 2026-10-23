terraform {
  required_version = ">= 1.5.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 5.0" }
    tls = { source = "hashicorp/tls", version = "~> 4.0" }
    local = { source = "hashicorp/local", version = "~> 2.0" }
  }
}

provider "aws" {
  region = "eu-central-1"
}

# --- Networking: reuse the default VPC ---
data "aws_vpc" "default" {
  default = true
}

data "aws_subnets" "default" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default.id]
  }
}

# --- Latest Ubuntu 22.04 LTS AMI (amd64) ---
data "aws_ami" "ubuntu" {
  most_recent = true
  owners      = ["099720109477"] # Canonical
  filter {
    name   = "name"
    values = ["ubuntu/images/hvm-ssd/ubuntu-jammy-22.04-amd64-server-*"]
  }
  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# --- SSH keypair (generated locally) ---
resource "tls_private_key" "spareai" {
  algorithm = "RSA"
  rsa_bits  = 4096
}

resource "aws_key_pair" "spareai" {
  key_name   = "spareai-key"
  public_key = tls_private_key.spareai.public_key_openssh
}

resource "local_file" "private_key" {
  content         = tls_private_key.spareai.private_key_pem
  filename        = "${path.module}/spareai-key.pem"
  file_permission = "0400"
}

# --- Security group ---
resource "aws_security_group" "spareai" {
  name        = "spareai-sg"
  description = "SpareAI PoC: SSH + Dispatcher from my IP, Agent port between instances"
  vpc_id      = data.aws_vpc.default.id

  # SSH from my laptop
  ingress {
    description = "SSH from my IP"
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["${var.my_ip}/32"]
  }

  # Dispatcher UI/API from my laptop
  ingress {
    description = "Dispatcher 8080 from my IP"
    from_port   = 8080
    to_port     = 8080
    protocol    = "tcp"
    cidr_blocks = ["${var.my_ip}/32"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "spareai-sg" }
}

# Agent port 8081: only reachable between instances sharing this SG
resource "aws_security_group_rule" "agent_self" {
  type                     = "ingress"
  from_port                = 8081
  to_port                  = 8081
  protocol                 = "tcp"
  source_security_group_id = aws_security_group.spareai.id
  security_group_id        = aws_security_group.spareai.id
  description              = "Agent 8081 reachable only from the other SpareAI instance"
}

# --- EC2 instances ---
resource "aws_instance" "spareai" {
  count                       = 2
  ami                         = data.aws_ami.ubuntu.id
  instance_type               = "c7i.xlarge"
  key_name                    = aws_key_pair.spareai.key_name
  vpc_security_group_ids      = [aws_security_group.spareai.id]
  subnet_id                   = data.aws_subnets.default.ids[0]
  associate_public_ip_address = true

  root_block_device {
    volume_size = 20
    volume_type = "gp3"
  }

  user_data = <<-EOF
    #!/bin/bash
    set -eux
    apt-get update
    apt-get install -y software-properties-common curl ca-certificates git
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update
    apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip

    # Install Ollama
    curl -fsSL https://ollama.com/install.sh | sh

    # Bind Ollama to localhost only (default) and start as a service
    systemctl enable --now ollama

    # Pull the pinned model (runs as the ollama service user)
    sleep 5
    sudo -u ollama ollama pull qwen2.5:3b-instruct-q4_K_M || ollama pull qwen2.5:3b-instruct-q4_K_M

    echo "spareai-provisioned" > /var/log/spareai-provisioned.marker
  EOF

  tags = {
    Name = "spareai-${count.index == 0 ? "a" : "b"}"
    Role = count.index == 0 ? "dispatcher+agent-a" : "agent-b"
  }
}
