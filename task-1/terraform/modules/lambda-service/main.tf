# modules/lambda-service: a container-image Lambda function, its own ECR
# repository, an IAM role scoped to exactly what it needs, and optional
# plain (SSM) / sensitive (Secrets Manager) config. Generic on purpose,
# see variables.tf's header comment, this is reused unmodified on Day 28.

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  ecr_repository_name = coalesce(var.ecr_repository_name, var.function_name)
  image_uri           = "${aws_ecr_repository.this.repository_url}:${var.image_tag}"
  log_group_name      = "/aws/lambda/${var.function_name}"

  # var.secrets is a sensitive map, so Terraform treats anything derived
  # from it, including its own key names, as sensitive too, and refuses
  # to use a sensitive value in for_each (it could leak into a resource
  # instance key). The key names themselves ("mlflow_tracking_credentials",
  # say) aren't secret, only the values are, so nonsensitive() here
  # declassifies just the keys; every reference to the actual value below
  # still goes through var.secrets[...] and stays sensitive.
  secret_keys = nonsensitive(keys(var.secrets))

  # Built by hand, not read from aws_ssm_parameter.this[key].arn: Floci's
  # SSM emulation doesn't return a parameter ARN (it comes back null,
  # confirmed via `terraform state show`), which would otherwise leave
  # the IAM policy below scoped to an empty resource, i.e. it would grant
  # nothing at all rather than the intended access. SSM parameter ARNs
  # are a fixed, documented shape, so constructing them here is correct
  # against real AWS too, not just a workaround for this one emulator gap.
  ssm_parameter_arns = [
    for key in keys(var.ssm_parameters) :
    "arn:aws:ssm:${data.aws_region.current.region}:${data.aws_caller_identity.current.account_id}:parameter/${var.function_name}/${key}"
  ]
  secret_arns = [
    for key in local.secret_keys : aws_secretsmanager_secret.this[key].arn
  ]
}

# ---------------------------------------------------------------------------
# ECR
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  #checkov:skip=CKV_AWS_51:MUTABLE tags are deliberate: task-9/README.md's build/push workflow re-pushes the same :v1 tag during iterative local testing against Floci, immutable tags would break that loop. A real release pipeline would tag by commit SHA and could safely go immutable; this repo's dev workflow doesn't yet.
  #checkov:skip=CKV_AWS_163:Floci does not emulate ECR image scanning (scan_on_push below is off for the same reason), and this module's images build from a pinned public.ecr.aws/lambda/python base, not arbitrary third-party layers. Real AWS should enable this; noted as a real-AWS gap, not silently dropped.
  #checkov:skip=CKV_AWS_136:Default AWS-managed encryption (SSE-S3-equivalent for ECR), not a customer-managed KMS key. This function's image contains no secrets (env vars/credentials are injected at runtime via Secrets Manager/SSM below, never baked into the image), so a CMK's added IAM/rotation surface isn't buying anything here.
  name                 = local.ecr_repository_name
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = false # Floci does not emulate ECR image scanning.
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# IAM, scoped to exactly what this function needs: write its own log
# group, read exactly the SSM parameters and secrets this instance
# declares. No "*" resources, no permissions for services this function
# doesn't touch.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "this" {
  name               = "${var.function_name}-lambda-role"
  assume_role_policy = data.aws_iam_policy_document.assume_role.json
  tags               = var.tags
}

data "aws_iam_policy_document" "permissions" {
  statement {
    sid     = "WriteOwnLogGroup"
    effect  = "Allow"
    actions = ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"]
    resources = [
      "arn:aws:logs:*:*:log-group:${local.log_group_name}:*",
    ]
  }

  dynamic "statement" {
    for_each = length(local.ssm_parameter_arns) > 0 ? [1] : []
    content {
      sid       = "ReadOwnSsmParameters"
      effect    = "Allow"
      actions   = ["ssm:GetParameter", "ssm:GetParameters"]
      resources = local.ssm_parameter_arns
    }
  }

  dynamic "statement" {
    for_each = length(local.secret_arns) > 0 ? [1] : []
    content {
      sid       = "ReadOwnSecrets"
      effect    = "Allow"
      actions   = ["secretsmanager:GetSecretValue"]
      resources = local.secret_arns
    }
  }
}

resource "aws_iam_role_policy" "this" {
  name   = "${var.function_name}-lambda-policy"
  role   = aws_iam_role.this.id
  policy = data.aws_iam_policy_document.permissions.json
}

# ---------------------------------------------------------------------------
# Plain config (SSM Parameter Store) and sensitive config (Secrets Manager)
# ---------------------------------------------------------------------------

resource "aws_ssm_parameter" "this" {
  #checkov:skip=CKV2_AWS_34:Type is String, not SecureString, deliberately: var.ssm_parameters is documented (variables.tf) as the plain-config half of this module's split, genuinely non-sensitive values (a model name, a log level), the sensitive half already goes through aws_secretsmanager_secret below instead. Encrypting a value that was never secret in the first place doesn't add real protection, see task-3/README.md's Secrets-Manager-vs-Parameter-Store section for the full reasoning.
  for_each = var.ssm_parameters

  name  = "/${var.function_name}/${each.key}"
  type  = "String"
  value = each.value
  tags  = var.tags
}

resource "aws_secretsmanager_secret" "this" {
  #checkov:skip=CKV_AWS_149:Default AWS-managed key, not a customer-managed CMK. This module's only current secret (mlflow_tracking_credentials, task-9) is an explicitly-labeled placeholder never read at runtime; a CMK's rotation/IAM overhead isn't justified for a value with no real blast radius today.
  #checkov:skip=CKV2_AWS_57:No automatic rotation configured, for the same reason: the one secret this module currently stores is a placeholder, never actually connected to by the running app (see task-9/README.md's "why the app doesn't read SSM/Secrets at runtime"). Rotating a value nothing reads doesn't buy anything; a real credential added here later should revisit this.
  for_each = toset(local.secret_keys)

  name = "${var.function_name}/${each.value}"
  tags = var.tags
}

resource "aws_secretsmanager_secret_version" "this" {
  for_each = toset(local.secret_keys)

  secret_id     = aws_secretsmanager_secret.this[each.value].id
  secret_string = var.secrets[each.value]
}

# ---------------------------------------------------------------------------
# Lambda function + Function URL
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "this" {
  #checkov:skip=CKV_AWS_117:Not VPC-attached: this function calls only public AWS service endpoints (or, against Floci, the emulator's single local endpoint) and RxGround's locally-run HTTP service, nothing inside a private VPC to reach. VPC attachment would add NAT/ENI cost and cold-start latency for no real network isolation benefit here.
  #checkov:skip=CKV_AWS_116:No DLQ configured: this function is invoked synchronously via a Function URL (request/response), not via SNS/SQS/EventBridge where a failed async invocation needs somewhere to land. A DLQ protects against a class of failure (dropped async retries) this invocation model doesn't have.
  #checkov:skip=CKV_AWS_173:Environment variables use Lambda's default encryption at rest (AWS-managed key), not a customer-managed KMS key. Consistent with the same call made for Secrets Manager/SSM above: the values here (LOG_LEVEL, cache host/port, LLM provider API keys passed via Terraform variables) don't currently justify a CMK's added rotation/IAM surface; a real production deployment handling genuine PHI would revisit this, see task-3/README.md.
  #checkov:skip=CKV_AWS_272:No code-signing configured: this is a container-image Lambda (package_type = "Image"), code-signing configs apply to zip-package Lambdas, not to image-based ones running from a versioned ECR repository.
  #checkov:skip=CKV_AWS_50:X-Ray tracing not enabled: this project's tracing story (agent step-by-step observation logs, returned directly in /review's response) is closer to Task 3's own structured trace than to X-Ray's distributed-tracing use case, which is more valuable across multiple services than for a single Lambda's internal tool-call loop.
  #checkov:skip=CKV_AWS_115:No reserved/provisioned concurrency limit set: this is a low-traffic demo deployment behind a Function URL, not a shared account where one function could starve others' concurrency budget, see task-2/README.md's load-test findings for this deployment's actual observed scale.
  function_name = var.function_name
  role          = aws_iam_role.this.arn
  package_type  = "Image"
  image_uri     = local.image_uri
  memory_size   = var.memory_size
  timeout       = var.timeout
  # Off by default (FleetPulse's Task 9 usage is unaffected): publishing
  # a numbered version on every apply is only useful to a caller that
  # actually points an alias's weighted routing_config at two versions,
  # see CareThread task-1/terraform/main.tf's canary alias for the
  # reason this exists.
  publish = var.publish

  environment {
    variables = var.environment_variables
  }

  tags = var.tags

  depends_on = [aws_iam_role_policy.this]
}

resource "aws_lambda_function_url" "this" {
  #checkov:skip=CKV_AWS_258:function_url_auth_type defaults to NONE, and variables.tf's own description already documents why: this is a local Floci-emulated deployment, not internet-reachable, AWS_IAM auth (the alternative) would need a real caller identity to sign requests with, meaningless against an emulator's fixed test credentials. A real-AWS deployment should set this variable to AWS_IAM or front the URL with an authorizer.
  count = var.create_function_url ? 1 : 0

  function_name      = aws_lambda_function.this.function_name
  authorization_type = var.function_url_auth_type
}
