resource "aws_cloudfront_origin_access_identity" "origin_access_identity" {
  comment = "access-identity-${replace(var.domainName, ".", "-")}.s3.amazonaws.com"
}

# CORS response headers policy — applied to every response from this distribution.
# Schema JSON is public API data; any origin may read it.
resource "aws_cloudfront_response_headers_policy" "cors" {
  name = "${replace(var.domainName, ".", "-")}-cors"

  cors_config {
    access_control_allow_credentials = false

    access_control_allow_headers {
      items = ["*"]
    }

    access_control_allow_methods {
      items = ["GET", "OPTIONS"]
    }

    access_control_allow_origins {
      items = ["*"]
    }

    origin_override = true
  }

  custom_headers_config {
    items {
      header   = "Cache-Control"
      value    = "max-age=60"
      override = false
    }
  }
}

resource "aws_cloudfront_distribution" "schema" {
  depends_on      = [aws_s3_bucket.schema_bucket]
  enabled         = true
  is_ipv6_enabled = true
  aliases         = [var.domainName]
  comment         = "SlideRule schema JSON server (${var.domainName})"

  origin {
    domain_name = aws_s3_bucket.schema_bucket.bucket_regional_domain_name
    origin_id   = "s3-${replace(var.domainName, ".", "-")}"

    s3_origin_config {
      origin_access_identity = aws_cloudfront_origin_access_identity.origin_access_identity.cloudfront_access_identity_path
    }
  }

  default_cache_behavior {
    target_origin_id       = "s3-${replace(var.domainName, ".", "-")}"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD", "OPTIONS"]
    viewer_protocol_policy = "redirect-to-https"
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }

    # max-age=60 while iterating (per task brief).
    min_ttl     = 0
    default_ttl = 60
    max_ttl     = 60

    response_headers_policy_id = aws_cloudfront_response_headers_policy.cors.id
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    acm_certificate_arn      = aws_acm_certificate_validation.cert.certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  # Missing keys (e.g. swot, cre, any unpublished path) return 404 with a JSON body.
  # The body is uploaded to /errors/not-found.json by `make deploy`.
  custom_error_response {
    error_code            = 403
    response_code         = 404
    response_page_path    = "/errors/not-found.json"
    error_caching_min_ttl = 0
  }

  custom_error_response {
    error_code            = 404
    response_code         = 404
    response_page_path    = "/errors/not-found.json"
    error_caching_min_ttl = 0
  }

  price_class = "PriceClass_100"
}
