resource "aws_s3_bucket" "schema_bucket" {
  bucket        = var.s3_bucket_name
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "schema_bucket_access_block" {
  bucket = aws_s3_bucket.schema_bucket.id

  block_public_acls       = true
  block_public_policy     = true
  restrict_public_buckets = true
  ignore_public_acls      = true
}

data "aws_iam_policy_document" "s3_policy" {
  statement {
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.schema_bucket.arn}/*"]

    principals {
      type        = "AWS"
      identifiers = [aws_cloudfront_origin_access_identity.origin_access_identity.iam_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "schema" {
  bucket = aws_s3_bucket.schema_bucket.id
  policy = data.aws_iam_policy_document.s3_policy.json
}

# S3 bucket CORS configuration so OPTIONS preflight requests return 200
# from the origin. Without this, S3 returns 405 Method Not Allowed on
# OPTIONS against an object key; CloudFront's response-headers policy
# still injects CORS headers, but a 405 preflight can be rejected by
# strict browsers. GET/HEAD cover the only real read methods on the
# distribution; preflight for those is what consumers care about.
resource "aws_s3_bucket_cors_configuration" "schema" {
  bucket = aws_s3_bucket.schema_bucket.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = ["*"]
    max_age_seconds = 3600
  }
}
