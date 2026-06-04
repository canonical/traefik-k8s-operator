# Terraform module for traefik-k8s

This is a Terraform module facilitating the deployment of traefik-k8s charm, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs). 

## Requirements
This module requires a `juju` model to be available. Refer to the [usage section](#usage) below for more details.

## API

### Inputs
The module offers the following configurable inputs:

| Name | Type | Description | Default |
| - | - | - | - |
| `app_name`| string | Name to give the deployed application | traefik |
| `channel`| string | Channel that the charm is deployed from |  |
| `config`| map(string) | Map of the charm configuration options | {} |
| `constraints`| string | String listing constraints for this application | arch=amd64 |
| `expose` | object({ cidrs = optional(string), endpoints = optional(string), spaces = optional(string) }) | Make the application publicly available over the network. When set, exposes the application; `cidrs`, `endpoints`, and `spaces` are comma-delimited lists restricting which CIDRs, charm endpoints, or spaces can access the exposed ports. | `null` |
| `model`| string | Reference to an existing model resource or data source for the model to deploy to |  |
| `resources`| map(string) | The charm's resources i.e., a resource revision number from CharmHub or a custom OCI image resource | {} |
| `revision`| number | Revision number of the charm |  |
| `storage_directives`| map(string) | Map of storage used by the application, which defaults to 1 GB, allocated by Juju. | {} |
| `units`| number | Unit count/scale | 1 |

### Outputs
Upon application, the module exports the following outputs:

| Name | Type | Description |
| - | - | - |
| `app_name`| string | Name of the deployed application |
| `endpoints`| map(string) | Map of all `provides` and `requires` endpoints |

## Usage

### Basic usage

<!-- BEGIN_TF_DOCS -->
## Providers

| Name | Version |
|------|---------|
| <a name="provider_juju"></a> [juju](#provider\_juju) | ~> 1.0 |

## Modules

No modules.

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_app_name"></a> [app\_name](#input\_app\_name) | Name to give the deployed application | `string` | `"traefik"` | no |
| <a name="input_channel"></a> [channel](#input\_channel) | Channel that the charm is deployed from | `string` | n/a | yes |
| <a name="input_config"></a> [config](#input\_config) | Map of the charm configuration options | `map(string)` | `{}` | no |
| <a name="input_constraints"></a> [constraints](#input\_constraints) | String listing constraints for this application | `string` | `"arch=amd64"` | no |

| <a name="input_model_uuid"></a> [model\_uuid](#input\_model\_uuid) | ID of the model to deploy to | `string` | n/a | yes |
| <a name="input_resources"></a> [resources](#input\_resources) | The charm's resources i.e., a resource revision number from CharmHub or a custom OCI image resource | `map(string)` | `{}` | no |
| <a name="input_revision"></a> [revision](#input\_revision) | Revision number of the charm | `number` | `null` | no |
| <a name="input_storage_directives"></a> [storage\_directives](#input\_storage\_directives) | Map of storage used by the application, which defaults to 1 GB, allocated by Juju | `map(string)` | `{}` | no |
| <a name="input_units"></a> [units](#input\_units) | Unit count/scale | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_app_name"></a> [app\_name](#output\_app\_name) | n/a |
| <a name="output_endpoints"></a> [endpoints](#output\_endpoints) | n/a |
<!-- END_TF_DOCS -->