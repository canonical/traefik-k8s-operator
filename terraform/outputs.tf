output "app_name" {
  value = juju_application.traefik.name
}

output "requires" {
  value = {
    certificates              = "certificates",
    experimental_forward_auth = "experimental-forward-auth",
    logging                   = "logging",
    tracing                   = "tracing",
  }
}

output "provides" {
  value = {
    grafana_dashboard = "grafana-dashboard",
    ingress           = "ingress",
    ingress_per_unit  = "ingress-per-unit",
    metrics_endpoint  = "metrics-endpoint",
    traefik_route     = "traefik-route",
  }
}
