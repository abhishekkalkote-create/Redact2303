# Aurora PostgreSQL 16, Serverless v2 (scales to 0.5 ACU idle in dev — see variables.tf).
# specs/02-architecture.md: RLS enforced at the app layer (SET app.org_id); this module
# just provisions the cluster, not the schema (Alembic owns that — see /api/alembic).

resource "aws_db_subnet_group" "this" {
  name       = "${var.name}-db"
  subnet_ids = var.private_subnet_ids
  tags       = var.tags
}

resource "aws_security_group" "db" {
  name_prefix = "${var.name}-db-"
  description = "Aurora PostgreSQL - ingress only from the app security group"
  vpc_id      = var.vpc_id
  tags        = var.tags

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = var.app_security_group_ids
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_kms_key" "db" {
  description             = "${var.name} Aurora storage encryption"
  deletion_window_in_days = 30
  enable_key_rotation     = true
  tags                    = var.tags
}

# Master credentials: RDS-managed (rotated by AWS, retrieved by app/workers at boot via
# Secrets Manager) rather than a Terraform-managed password in state.
resource "aws_rds_cluster" "this" {
  cluster_identifier              = "${var.name}-db"
  engine                          = "aurora-postgresql"
  engine_mode                     = "provisioned"
  engine_version                  = var.engine_version
  database_name                   = "redactproof"
  master_username                 = "redactproof_admin"
  manage_master_user_password     = true
  db_subnet_group_name            = aws_db_subnet_group.this.name
  vpc_security_group_ids          = [aws_security_group.db.id]
  storage_encrypted               = true
  kms_key_id                      = aws_kms_key.db.arn
  backup_retention_period         = var.backup_retention_days
  preferred_backup_window         = "08:00-09:00"
  deletion_protection             = var.deletion_protection
  skip_final_snapshot             = !var.deletion_protection
  final_snapshot_identifier       = var.deletion_protection ? "${var.name}-db-final" : null
  db_cluster_parameter_group_name = aws_rds_cluster_parameter_group.this.name

  serverlessv2_scaling_configuration {
    min_capacity = var.min_acu
    max_capacity = var.max_acu
  }

  tags = var.tags
}

# force_ssl: TLS 1.2+ everywhere (specs/08-security-compliance.md).
resource "aws_rds_cluster_parameter_group" "this" {
  name        = "${var.name}-db-params"
  family      = "aurora-postgresql16"
  description = "${var.name} Aurora PG16 params"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }

  tags = var.tags
}

resource "aws_rds_cluster_instance" "writer" {
  cluster_identifier = aws_rds_cluster.this.id
  identifier         = "${var.name}-db-writer"
  instance_class     = "db.serverless"
  engine             = aws_rds_cluster.this.engine
  engine_version     = aws_rds_cluster.this.engine_version
  tags               = var.tags
}
