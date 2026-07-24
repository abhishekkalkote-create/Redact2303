output "cluster_endpoint" {
  value = aws_rds_cluster.this.endpoint
}

output "reader_endpoint" {
  value = aws_rds_cluster.this.reader_endpoint
}

output "master_user_secret_arn" {
  description = "Secrets Manager secret ARN holding the RDS-managed master credentials"
  value       = aws_rds_cluster.this.master_user_secret[0].secret_arn
}

output "database_name" {
  value = aws_rds_cluster.this.database_name
}

output "security_group_id" {
  value = aws_security_group.db.id
}
