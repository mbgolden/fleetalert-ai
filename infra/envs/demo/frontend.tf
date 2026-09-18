module "frontend" {
  source = "../../modules/frontend"
  name   = "${var.project_name}-demo"
  tags   = local.common_tags
}
