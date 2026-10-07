variable "name" {
  description = "Name prefix for all resources."
  type        = string
  default     = "incident-manager"
}

variable "region" {
  description = "AWS region."
  type        = string
  default     = "eu-central-1"
}

variable "vpc_cidr" {
  description = "CIDR block of the VPC. Subnets are carved out of it as /20s."
  type        = string
  default     = "10.40.0.0/16"
}

variable "az_count" {
  description = "Number of availability zones to spread over. Three lets the cluster lose one and keep a quorum of database instances."
  type        = number
  default     = 3

  validation {
    condition     = var.az_count >= 2 && var.az_count <= 4
    error_message = "az_count must be between 2 and 4."
  }
}

variable "kubernetes_version" {
  description = "EKS control plane version."
  type        = string
  default     = "1.31"
}

variable "api_public_access_cidrs" {
  description = "CIDR blocks allowed to reach the EKS API endpoint. Narrow this to office/VPN ranges."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "node_instance_types" {
  description = "Instance types for the managed node group."
  type        = list(string)
  default     = ["t3.large"]
}

variable "node_count" {
  description = "Minimum, desired and maximum number of worker nodes."
  type = object({
    min     = number
    desired = number
    max     = number
  })
  default = {
    min     = 3
    desired = 3
    max     = 6
  }
}

variable "backup_retention_days" {
  description = "Days to keep superseded object versions in the backup bucket. CloudNativePG's own retention policy deletes current objects; this cleans up after it."
  type        = number
  default     = 30
}

variable "database_service_account" {
  description = "Namespace and name of the service account the database pods run as. CloudNativePG names it after the Cluster resource."
  type = object({
    namespace = string
    name      = string
  })
  default = {
    namespace = "incident-manager"
    name      = "incident-manager-db"
  }
}
