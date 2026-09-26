module "frontend" {
  source = "../../modules/frontend"
  name   = "${var.project_name}-demo"
  tags   = local.common_tags

  # Two-phase: apply once with attach off to get the ACM validation CNAME
  # (see the acm_validation_records output), add it in DNS, then flip
  # frontend_attach_custom_domain on and apply again. See ADR-0009.
  custom_domain        = var.frontend_custom_domain
  attach_custom_domain = var.frontend_attach_custom_domain
}
