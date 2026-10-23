variable "my_ip" {
  description = "Your laptop's current public IPv4 address (no CIDR suffix). Pass explicitly on every apply so a stale cached value never silently expands SSH access."
  type        = string

  validation {
    condition     = can(regex("^([0-9]{1,3}\\.){3}[0-9]{1,3}$", var.my_ip))
    error_message = "my_ip must be a bare IPv4 like 203.0.113.4 (no /32)."
  }
}
