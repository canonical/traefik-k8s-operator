# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Legacy output: name of the deployed application"
  value       = juju_application.traefik.name
}

output "application" {
  description = "The deployed traefik-k8s application."
  value       = juju_application.traefik
}

output "provides" {
  description = "Map of the provides endpoints exposed by the charm."
  value = {
    grafana_dashboard = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "grafana-dashboard"
      controller = null
    }
    ingress = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "ingress"
      controller = null
    }
    ingress_per_unit = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "ingress-per-unit"
      controller = null
    }
    metrics_endpoint = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "metrics-endpoint"
      controller = null
    }
    traefik_route = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "traefik-route"
      controller = null
    }
  }
}

output "requires" {
  description = "Map of the requires endpoints consumed by the charm."
  value = {
    certificates = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "certificates"
      controller = null
    }
    charm_tracing = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "charm-tracing"
      controller = null
    }
    experimental_forward_auth = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "experimental-forward-auth"
      controller = null
    }
    logging = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "logging"
      controller = null
    }
    receive_ca_cert = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "receive-ca-cert"
      controller = null
    }
    upstream_ingress = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "upstream-ingress"
      controller = null
    }
    workload_tracing = {
      kind       = "endpoint"
      name       = juju_application.traefik.name
      endpoint   = "workload-tracing"
      controller = null
    }
  }
}
