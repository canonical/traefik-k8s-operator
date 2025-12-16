resource "juju_application" "traefik" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
