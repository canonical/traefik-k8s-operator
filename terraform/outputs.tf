output "traefik_application_name" {
  description = "Name of the deployed application."
  value       = juju_application.traefik-k8s.name
}