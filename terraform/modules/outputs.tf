output "s3_bucket_name" {
  value = aws_s3_bucket.schema_bucket.bucket
}

output "cloudfront_distribution_id" {
  value = aws_cloudfront_distribution.schema.id
}

output "cloudfront_domain_name" {
  value = aws_cloudfront_distribution.schema.domain_name
}
