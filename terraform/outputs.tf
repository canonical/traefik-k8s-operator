output "application" {
  description = "The deployed traefik-k8s application."
  value       = juju_application.traefik
}

output "provides" {
  description = "Map of the provides endpoints exposed by the charm."
  value = {
    ingress           = "ingress",
    ingress_per_unit  = "ingress-per-unit",
    metrics_endpoint  = "metrics-endpoint",
    traefik_route     = "traefik-route",
    grafana_dashboard = "grafana-dashboard",
  }
}

output "requires" {
  description = "Map of the requires endpoints consumed by the charm."
  value = {
    certificates              = "certificates",
    experimental_forward_auth = "experimental-forward-auth",
    logging                   = "logging",
    charm_tracing             = "charm-tracing",
    workload_tracing          = "workload-tracing",
    receive_ca_cert           = "receive-ca-cert",
    upstream_ingress          = "upstream-ingress",
  }
}
