output "instance_a_public_ip" {
  description = "Public IP of spareai-a (Dispatcher + Agent A)"
  value       = aws_instance.spareai[0].public_ip
}

output "instance_b_public_ip" {
  description = "Public IP of spareai-b (Agent B)"
  value       = aws_instance.spareai[1].public_ip
}

output "instance_a_private_ip" {
  description = "Private IP of spareai-a — Dispatcher uses this to reach Agent A"
  value       = aws_instance.spareai[0].private_ip
}

output "instance_b_private_ip" {
  description = "Private IP of spareai-b — Dispatcher uses this to reach Agent B over port 8081"
  value       = aws_instance.spareai[1].private_ip
}

output "ssh_a" {
  description = "SSH into spareai-a"
  value       = "ssh -i infra/spareai-key.pem ubuntu@${aws_instance.spareai[0].public_ip}"
}

output "ssh_b" {
  description = "SSH into spareai-b"
  value       = "ssh -i infra/spareai-key.pem ubuntu@${aws_instance.spareai[1].public_ip}"
}

output "dispatcher_url" {
  description = "Open this in your browser after starting the Dispatcher on spareai-a"
  value       = "http://${aws_instance.spareai[0].public_ip}:8080/"
}
