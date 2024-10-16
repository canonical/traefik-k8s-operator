output "app_name" {
  value = juju_application.traefik.name
}

output "ingress_endpoint" {
  description = "Name of the endpoint used by Traefik to provide ingress for the remote applications requesting it."
  value       = "ingress"
}

output "ingress_per_unit_endpoint" {
  description = "Name of the endpoint used by Traefik to provide ingress for the remote units requesting it."
  value       = "ingress-per-unit"
}

output "traefik_route_endpoint" {
  value       = "traefik-route"
}
