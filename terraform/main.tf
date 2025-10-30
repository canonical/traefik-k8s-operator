data "juju_model" "model" {
  # Don't fetch the model if model_uuid is provided
  count = var.model_uuid != "" ? 0 : 1
  name  = var.model
  owner = var.model_owner
}

resource "juju_application" "traefik" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid != "" ? var.model_uuid : element(concat(data.juju_model.model.*.id, tolist([""])), 0)
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }
}
