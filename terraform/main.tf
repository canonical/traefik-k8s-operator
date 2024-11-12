resource "juju_application" "traefik" {
  name  = var.app_name
  model = var.model_name
  trust = true
  charm {
    name     = "traefik-k8s"
    channel  = var.channel
    revision = var.revision
  }
  units  = var.units
  config = var.config
}