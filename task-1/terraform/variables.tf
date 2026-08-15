variable "image_tag" {
  description = "Tag of the CareThread Lambda image already built and pushed to Floci's ECR. No default, same reasoning as FleetPulse's task-9/terraform/variables.tf: CI and local runs must both supply this explicitly."
  type        = string
}

variable "previous_version" {
  description = "The Lambda version currently serving traffic before this apply, e.g. \"3\". Leave null for a first deploy (the alias routes 100% of traffic to the version this apply just published, no canary weighting is possible yet with only one version). Set it on every deploy after the first to get real weighted canary routing between the outgoing and incoming version."
  type        = string
  default     = null
}

variable "canary_weight" {
  description = "Fraction of traffic (0.0-1.0) sent to previous_version; the remainder goes to the version this apply just published. Ignored when previous_version is null."
  type        = number
  default     = 0.1

  validation {
    condition     = var.canary_weight >= 0 && var.canary_weight <= 1
    error_message = "canary_weight must be between 0 and 1."
  }
}
