output "app_name" {
  value = juju_application.traefik.name
}

output "endpoints" {
  value = {
    # Requires
    certificates              = "certificates",
    charm_tracing             = "charm-tracing",
    experimental_forward_auth = "experimental-forward-auth",
    logging                   = "logging",
    receive_ca_cert           = "receive-ca-cert",
    workload_tracing          = "workload-tracing",
    upstream-ingress          = "upstream-ingress"
    # Provides
    grafana_dashboard = "grafana-dashboard",
    ingress           = "ingress",
    ingress_per_unit  = "ingress-per-unit",
    metrics_endpoint  = "metrics-endpoint",
    traefik_route     = "traefik-route",
  }
}
