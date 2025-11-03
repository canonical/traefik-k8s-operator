variable "app_name" {
  description = "Name to give the deployed application"
  type        = string
  default     = "traefik"
}

variable "channel" {
  description = "Channel that the charm is deployed from"
  type        = string
}

variable "config" {
  description = "Map of the charm configuration options"
  type        = map(string)
  default     = {}
}

# We use constraints to set AntiAffinity in K8s
# https://discourse.charmhub.io/t/pod-priority-and-affinity-in-juju-charms/4091/13?u=jose
variable "constraints" {
  description = "String listing constraints for this application"
  type        = string
  # FIXME: Passing an empty constraints value to the Juju Terraform provider currently
  # causes the operation to fail due to https://github.com/juju/terraform-provider-juju/issues/344
  default = "arch=amd64"
}

variable "model_uuid" {
  description = "ID of the model to deploy to, takes priority over model + model_owner"
  type        = string
  default     = ""
}

variable "model" {
  description = "Name of the model to deploy to."
  type        = string
  default     = ""
}

variable "model_owner" {
  description = "ID of the model owner, used in conjunction with model name."
  type        = string
  default     = "admin"
}

variable "revision" {
  description = "Revision number of the charm"
  type        = number
  default     = null
}

variable "storage_directives" {
  description = "Map of storage used by the application, which defaults to 1 GB, allocated by Juju"
  type        = map(string)
  default     = {}
}

variable "units" {
  description = "Unit count/scale"
  type        = number
  default     = 1
}
