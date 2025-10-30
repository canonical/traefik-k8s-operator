data "juju_model" "model" {
  count = var.model_uuid != "" ? 1 : 0
  name  = var.model
  owner = var.model_owner
}

resource "juju_application" "traefik" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid != "" ? var.model_uuid : data.juju_model.model[0].id
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
