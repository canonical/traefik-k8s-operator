output "app_name" {
  value = juju_application.traefik.name
}

output "endpoints" {
  value = {
    # Requires
    certificates              = "certificates",
    experimental_forward_auth = "experimental-forward-auth",
    logging                   = "logging",
    tracing                   = "tracing",
    
    # Provides
    grafana_dashboard = "grafana-dashboard",
    ingress           = "ingress",
    ingress_per_unit  = "ingress-per-unit",
    metrics_endpoint  = "metrics-endpoint",
    traefik_route     = "traefik-route",
  }
}
