output "domain_apex" {
  value = var.domainApex
}

output "domain_name" {
  value = var.domainName
}

output "domain_root" {
  value = var.domain_root
}

output "s3_bucket_name" {
  value = module.cloudfront.s3_bucket_name
}

output "cloudfront_distribution_id" {
  value = module.cloudfront.cloudfront_distribution_id
}

output "cloudfront_domain_name" {
  value = module.cloudfront.cloudfront_domain_name
}
