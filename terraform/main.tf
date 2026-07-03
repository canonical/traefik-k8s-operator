resource "juju_application" "traefik" {
  name = var.app_name
  # Juju requires `juju-external-hostname` to be set before a Kubernetes application
  # can be exposed. Derive it from the charm's own `external_hostname` config so callers
  # only need to set one hostname (mirrors canonical/is-terraform-modules' COS module).
  # The `expose` variable validation guarantees `external_hostname` is set when exposing.
  config = var.expose ? merge(var.config, {
    "juju-external-hostname" = var.config["external_hostname"]
  }) : var.config
  constraints        = var.constraints
  model_uuid         = var.model_uuid
  resources          = var.resources
  storage_directives = var.storage_directives
  trust              = true
  units              = var.units

  charm {
    base     = var.base
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }

  dynamic "expose" {
    for_each = var.expose ? [1] : []
    content {}
  }
}
