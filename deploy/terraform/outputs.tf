output "cluster_name" {
  description = "EKS cluster name, for `aws eks update-kubeconfig --name`."
  value       = aws_eks_cluster.this.name
}

output "cluster_endpoint" {
  description = "EKS API server endpoint."
  value       = aws_eks_cluster.this.endpoint
}

output "availability_zones" {
  description = "Zones the nodes are spread over."
  value       = local.azs
}

output "backup_bucket" {
  description = "Bucket for database backups. Helm value postgres.backup.destinationPath is s3://<this>/cnpg."
  value       = aws_s3_bucket.backups.bucket
}

output "backup_role_arn" {
  description = "IAM role for the database service account. Helm value postgres.backup.iamRoleArn."
  value       = aws_iam_role.db_backup.arn
}
