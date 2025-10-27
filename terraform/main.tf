data "juju_model" "model" {
  name = var.model
}

resource "juju_application" "traefik" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = data.juju_model.model.id
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }
}