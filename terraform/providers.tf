# Authentication is supplied externally through the AWS credential chain.
provider "aws" {
  region = var.aws_region
}
