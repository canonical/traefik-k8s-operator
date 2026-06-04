resource "juju_application" "traefik" {
  name               = var.app_name
  config             = var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  resources          = var.resources
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }

  dynamic "expose" {
    for_each = var.expose != null ? [var.expose] : []
    content {
      cidrs     = expose.value.cidrs
      endpoints = expose.value.endpoints
      spaces    = expose.value.spaces
    }
  }
}
