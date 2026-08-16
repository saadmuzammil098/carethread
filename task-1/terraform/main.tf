# CareThread-specific wiring of FleetPulse's Task 9 modules/lambda-
# service module, copied unmodified into this repo (see
# modules/lambda-service's header comment) except for one additive,
# backward-compatible change: a `publish` variable, defaulted to false
# so FleetPulse's own usage is untouched, added here so CareThread can
# publish numbered versions and route between them below. This is the
# actual reuse the roadmap describes: same module, new function name,
# new image, new environment variables.

module "carethread_api" {
  source = "./modules/lambda-service"

  function_name = "carethread-api"
  image_tag     = var.image_tag
  publish       = true

  # Bumped for Task 3's /review: a chart-review agent run makes several
  # sequential LLM calls (each with its own provider-fallback chain)
  # plus a live HTTP call to RxGround, observed taking up to ~90s
  # against local Ollama cold starts in testing. /flag and /health stay
  # fast regardless, this only raises the ceiling for /review's slower
  # path. A Lambda Function URL (not API Gateway) has no lower cap of
  # its own, real AWS supports up to 900s.
  memory_size = 512
  timeout     = 120

  environment_variables = {
    LOG_LEVEL                             = "INFO"
    CARETHREAD_REDIS_HOST                 = aws_elasticache_replication_group.narrative_cache.primary_endpoint_address
    CARETHREAD_REDIS_PORT                 = "6379"
    CARETHREAD_REDIS_IAM_USER             = aws_elasticache_user.app.user_id
    CARETHREAD_REDIS_REPLICATION_GROUP_ID = aws_elasticache_replication_group.narrative_cache.replication_group_id
    GEMINI_API_KEY                        = var.gemini_api_key
    GROQ_API_KEY                          = var.groq_api_key
  }

  tags = {
    Project = "carethread"
    Task    = "1"
  }
}

# Weighted-alias canary: on a first deploy (previous_version is null)
# all traffic goes to the version this apply just published, there's
# nothing to canary against yet. On every deploy after that, pass
# -var="previous_version=<the version currently live>" and traffic
# splits canary_weight/1-canary_weight between the outgoing and
# incoming version, Lambda's own free, built-in canary mechanism, no
# CodeDeploy setup required.
resource "aws_lambda_alias" "live" {
  name             = "live"
  function_name    = module.carethread_api.function_name
  function_version = module.carethread_api.version

  dynamic "routing_config" {
    for_each = var.previous_version != null ? [1] : []
    content {
      additional_version_weights = {
        (var.previous_version) = var.canary_weight
      }
    }
  }
}
