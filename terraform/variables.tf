variable "domainApex" {
  description = "Apex domain, e.g. testsliderule.org"
  default     = "testsliderule.org"
}

variable "domainName" {
  description = "Full domain of the schema distribution, e.g. schema.testsliderule.org"
  default     = "schema.testsliderule.org"
}

variable "domain_root" {
  description = "Domain label used in tags, e.g. testsliderule"
  default     = "testsliderule"
}

variable "s3_bucket_name" {
  type        = string
  description = "Name of the S3 bucket that stores the schema JSON tree"
  validation {
    condition     = length(var.s3_bucket_name) > 0
    error_message = "The s3_bucket_name variable must not be empty."
  }
}

variable "cost_grouping" {
  description = "Cost tag grouping"
  type        = string
  default     = "schema-server"
}
