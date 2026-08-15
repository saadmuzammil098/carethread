# Same Floci-emulated endpoint every earlier project's Terraform points
# at (see fleetpulse/task-9/terraform/provider.tf), fixed test
# credentials, no real AWS account involved.
provider "aws" {
  region = "us-east-1"

  access_key = "test"
  secret_key = "test"

  skip_credentials_validation = true
  skip_metadata_api_check     = true
  skip_requesting_account_id  = true
  skip_region_validation      = true

  endpoints {
    ecr            = "http://localhost.floci.io:4566"
    iam            = "http://localhost.floci.io:4566"
    lambda         = "http://localhost.floci.io:4566"
    s3             = "http://localhost.floci.io:4566"
    secretsmanager = "http://localhost.floci.io:4566"
    ssm            = "http://localhost.floci.io:4566"
    sts            = "http://localhost.floci.io:4566"
  }
}
