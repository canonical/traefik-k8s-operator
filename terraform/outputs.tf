# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.traefik-k8s.name
}

# Required integration endpoints

output "certificates_endpoint" {
  description = "Name of the endpoint to get the X.509 certificate using `tls-certificates` interface."
  value       = "certificates"
}

output "experimental_forward_auth_endpoint" {
  description = "Name of the endpoint for `forward_auth` interface."
  value       = "experimental-forward-auth"
}

output "logging_endpoint" {
  description = "Name of the endpoint for `loki_push_api` interface."
  value       = "logging"
}

output "tracing_endpoint" {
  description = "Name of the endpoint for `tracing` interface."
  value       = "tracing"
}

output "receive_ca_cert_endpoint" {
  description = "Name of the endpoint for `certificate_transfer` interface."
  value       = "receive-ca-cert"
}

# Provided integration endpoints

output "ingress_endpoint" {
  description = "Name of the endpoint for `ingress` interface."
  value       = "ingress"
}

output "ingress_per_unit_endpoint" {
  description = "Name of the endpoint for `ingress_per_unit` interface."
  value       = "ingress-per-unit"
}

output "metrics_endpoint_endpoint" {
  description = "Name of the endpoint for `prometheus_scrape` interface."
  value       = "metrics-endpoint"
}

output "traefik_route_endpoint" {
  description = "Name of the endpoint for `traefik_route` interface."
  value       = "traefik-route"
}

output "grafana_dashboard_endpoint" {
  description = "Name of the endpoint for `grafana_dashboard` interface."
  value       = "grafana-dashboard"
}
