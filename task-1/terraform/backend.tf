# State isolation from FleetPulse (the roadmap's "your call: workspaces
# or directory-per-environment"): a separate bucket (carethread-tfstate,
# not fleetpulse-tfstate) rather than a Terraform workspace inside the
# same backend. FleetPulse and CareThread are already separate repos
# with separate CI, so a separate bucket is the natural boundary, one
# less thing to remember (`terraform workspace select` before every
# command) and one that can't accidentally be forgotten in CI. See
# README.md's "bootstrap" step: `aws s3 mb s3://carethread-tfstate` must
# run once before `terraform init`, Terraform's S3 backend does not
# create its own state bucket.
terraform {
  backend "s3" {
    bucket       = "carethread-tfstate"
    key          = "task-1/lambda-service.tfstate"
    region       = "us-east-1"
    use_lockfile = true

    endpoints = {
      s3 = "http://localhost.floci.io:4566"
    }

    access_key                  = "test"
    secret_key                  = "test"
    skip_credentials_validation = true
    skip_metadata_api_check     = true
    skip_requesting_account_id  = true
    skip_region_validation      = true
    use_path_style              = true
  }
}
