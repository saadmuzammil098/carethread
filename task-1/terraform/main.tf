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

  memory_size = 256
  timeout     = 20

  environment_variables = {
    LOG_LEVEL = "INFO"
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
