# Task 2: real ElastiCache for Redis, IAM-authenticated (no plain
# password anywhere, matching the credential hygiene this repo already
# uses for Secrets Manager, real least-privilege auth instead of a
# shared secret string). Lives alongside Task 1's Lambda/alias config
# rather than a separate task-2/terraform, this is the same deployed
# app gaining a cache, not a second stack, same reasoning as
# task-1/src/narrative.py's header comment for why Task 2's Python
# lives in task-1/src too.

resource "aws_elasticache_user" "app" {
  user_id       = "carethread-app"
  user_name     = "carethread-app"
  engine        = "redis"
  access_string = "on ~carethread:* +@read +@write -@dangerous"

  authentication_mode {
    type = "iam"
  }
}

resource "aws_elasticache_user_group" "app" {
  engine        = "redis"
  user_group_id = "carethread-cache-users"
  user_ids      = [aws_elasticache_user.app.user_id]
}

resource "aws_elasticache_replication_group" "narrative_cache" {
  #checkov:skip=CKV_AWS_191:Encrypted with the default AWS-managed key (at_rest_encryption_enabled below), not a customer-managed CMK. A cached LLM narrative is not the patient record itself (see task-3/README.md's Secrets-Manager-vs-Parameter-Store section for what actually gets the stricter treatment); a CMK adds real operational cost (key rotation, IAM policy surface) this cache's contents don't justify.
  #checkov:skip=CKV2_AWS_50:Single node (num_cache_clusters=1), no Multi-AZ failover, a deliberate minimal-footprint choice already documented in task-2/README.md for this same resource: this is a performance cache for a re-derivable LLM narrative, not a durability-critical data store, a cache miss on failover is a slower response, not data loss.
  replication_group_id       = "carethread-cache"
  description                = "CareThread narrative cache (Task 2)"
  engine                     = "redis"
  node_type                  = "cache.t3.micro"
  num_cache_clusters         = 1
  transit_encryption_enabled = true
  at_rest_encryption_enabled = true
  user_group_ids             = [aws_elasticache_user_group.app.user_group_id]

  tags = {
    Project = "carethread"
    Task    = "2"
  }
}

# The Lambda's own IAM role (from the reused module) gets exactly one
# additional permission: connect as this one IAM-auth user. Added at
# the root, not inside modules/lambda-service, ElastiCache access isn't
# something every lambda-service deployment needs, keeping it out of
# the generic module the same way Task 1 kept the canary alias itself
# out of it.
resource "aws_iam_role_policy" "elasticache_connect" {
  name = "carethread-api-elasticache-connect"
  role = element(split("/", module.carethread_api.iam_role_arn), 1)

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ConnectAsCarethreadAppUser"
        Effect = "Allow"
        Action = "elasticache:Connect"
        Resource = [
          aws_elasticache_user.app.arn,
          aws_elasticache_replication_group.narrative_cache.arn,
        ]
      }
    ]
  })
}
