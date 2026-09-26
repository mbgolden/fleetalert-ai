# React SPA hosting: a private S3 bucket, readable only by CloudFront via
# Origin Access Control (OAC) -- not a public bucket, no legacy OAI. No
# custom domain by default: this uses CloudFront's own default
# *.cloudfront.net domain unless var.attach_custom_domain is set.
#
# The 403/404 -> /index.html rewrite below is what makes client-side
# routing (react-router) work on a hard refresh of e.g. /alerts/ALERT-1 --
# S3 has no such route, so without this CloudFront would just show S3's
# raw AccessDenied/NoSuchKey response instead of letting the SPA's own
# router handle the path.
#
# Optional custom domain (see ADR-0009): var.custom_domain requests an ACM
# cert; var.attach_custom_domain (a second apply, after the validation
# CNAME exists in DNS) attaches it to the distribution as an alias.

resource "aws_s3_bucket" "site" {
  bucket = "${var.name}-frontend"
  tags   = var.tags
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${var.name}-frontend-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

resource "aws_acm_certificate" "site" {
  count             = var.custom_domain != null ? 1 : 0
  domain_name       = var.custom_domain
  validation_method = "DNS"
  tags              = var.tags

  lifecycle {
    create_before_destroy = true
  }
}

# Blocks until the validation CNAME is visible in DNS, so it only exists
# once attach_custom_domain is flipped on -- otherwise a first apply would
# hang for up to 45 minutes waiting on a record nobody has added yet.
resource "aws_acm_certificate_validation" "site" {
  count           = var.attach_custom_domain ? 1 : 0
  certificate_arn = aws_acm_certificate.site[0].arn
}

resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  aliases             = var.attach_custom_domain ? [var.custom_domain] : []
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # cheapest tier -- US/Canada/Europe only, fine for a demo
  tags                = var.tags

  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "s3-site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }

  default_cache_behavior {
    target_origin_id       = "s3-site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true

    forwarded_values {
      query_string = false
      cookies {
        forward = "none"
      }
    }
  }

  custom_error_response {
    error_code         = 403
    response_code      = 200
    response_page_path = "/index.html"
  }

  custom_error_response {
    error_code         = 404
    response_code      = 200
    response_page_path = "/index.html"
  }

  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }

  viewer_certificate {
    cloudfront_default_certificate = var.attach_custom_domain ? null : true
    acm_certificate_arn            = var.attach_custom_domain ? aws_acm_certificate_validation.site[0].certificate_arn : null
    ssl_support_method             = var.attach_custom_domain ? "sni-only" : null
    minimum_protocol_version       = var.attach_custom_domain ? "TLSv1.2_2021" : null
  }
}

data "aws_iam_policy_document" "site_bucket_policy" {
  statement {
    sid       = "AllowCloudFrontOAC"
    effect    = "Allow"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.site.arn}/*"]

    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.site.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = data.aws_iam_policy_document.site_bucket_policy.json
}
