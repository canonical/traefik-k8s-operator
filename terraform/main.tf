resource "juju_application" "traefik-k8s" {
  name  = "traefik-k8s"
  model = var.model_name

  charm {
    name    = "traefik-k8s"
    channel = var.channel
  }
  config = var.traefik-config
  units  = 1
  trust  = true

}


