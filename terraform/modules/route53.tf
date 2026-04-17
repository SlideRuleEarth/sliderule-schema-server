data "aws_route53_zone" "public" {
  name         = var.domainApex
  private_zone = false
}

resource "aws_acm_certificate" "schema" {
  domain_name       = var.domainName
  validation_method = "DNS"

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_route53_record" "cert_validation" {
  allow_overwrite = true
  name            = tolist(aws_acm_certificate.schema.domain_validation_options)[0].resource_record_name
  records         = [tolist(aws_acm_certificate.schema.domain_validation_options)[0].resource_record_value]
  type            = tolist(aws_acm_certificate.schema.domain_validation_options)[0].resource_record_type
  zone_id         = data.aws_route53_zone.public.id
  ttl             = 60
}

resource "aws_acm_certificate_validation" "cert" {
  certificate_arn         = aws_acm_certificate.schema.arn
  validation_record_fqdns = [aws_route53_record.cert_validation.fqdn]
}

resource "aws_route53_record" "schema" {
  zone_id = data.aws_route53_zone.public.id
  name    = var.domainName
  type    = "A"

  alias {
    name                   = aws_cloudfront_distribution.schema.domain_name
    zone_id                = aws_cloudfront_distribution.schema.hosted_zone_id
    evaluate_target_health = false
  }
}
