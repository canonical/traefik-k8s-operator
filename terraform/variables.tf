variable "model_name" {
  description = "Name of Juju model to deploy application to."
  type        = string
  default     = ""
}

variable "app_name" {
  description = "Name of the application in the Juju model"
  type        = string
  default     = "traefik"
}

variable "channel" {
  description = "The channel to use when deploying a charm."
  type        = string
  default     = "latest/stable"
}

variable "config" {
  description = "Additional configuration for the Traefik charm. Please see the available options: https://charmhub.io/traefik-k8s/configure."
  type        = map(string)
  default     = {}
}