output "app_name" {
  value = juju_application.traefik.name
}

output "endpoints" {
  value = {
    certificates              = "certificates",
    experimental_forward_auth = "experimental-forward-auth",
    grafana_dashboard         = "grafana-dashboard",
    ingress                   = "ingress",
    ingress_per_unit          = "ingress-per-unit",
    logging                   = "logging",
    metrics_endpoint          = "metrics-endpoint",
    tracing                   = "tracing",
    traefik_route             = "traefik-route",
  }
}
