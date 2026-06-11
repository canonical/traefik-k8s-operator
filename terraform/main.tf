locals {
  # Juju requires `juju-external-hostname` to be set before a Kubernetes application
  # can be exposed. Derive it from the charm's own `external_hostname` config so callers
  # only need to set one hostname (mirrors canonical/is-terraform-modules' COS module).
  external_hostname = lookup(var.config, "external_hostname", "")
  should_expose     = var.expose && local.external_hostname != ""
  config = local.should_expose ? merge(var.config, {
    "juju-external-hostname" = local.external_hostname
  }) : var.config
}

resource "juju_application" "traefik" {
  name               = var.app_name
  config             = local.config
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
    for_each = local.should_expose ? [1] : []
    content {}
  }
}
