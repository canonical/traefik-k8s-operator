# Terraform module for traefik-k8s

This is a Terraform module facilitating the deployment of traefik-k8s charm, using the [Terraform juju provider](https://github.com/juju/terraform-provider-juju/). For more information, refer to the provider [documentation](https://registry.terraform.io/providers/juju/juju/latest/docs). 

This module requires a `juju` model to be available. Refer to the [usage section](#usage) below for more details.

<!-- BEGIN_TF_DOCS -->
## Requirements

| Name | Version |
|------|---------|
| <a name="requirement_terraform"></a> [terraform](#requirement\_terraform) | ~> 1.11 |
| <a name="requirement_juju"></a> [juju](#requirement\_juju) | >= 1.0, < 3.0 |

## Providers

| Name | Version |
|------|---------|
| <a name="provider_juju"></a> [juju](#provider\_juju) | >= 1.0, < 3.0 |

## Modules

No modules.

## Resources

| Name | Type |
|------|------|
| [juju_application.traefik](https://registry.terraform.io/providers/juju/juju/latest/docs/resources/application) | resource |

## Inputs

| Name | Description | Type | Default | Required |
|------|-------------|------|---------|:--------:|
| <a name="input_app_name"></a> [app\_name](#input\_app\_name) | Name to give the deployed application | `string` | `"traefik"` | no |
| <a name="input_channel"></a> [channel](#input\_channel) | Channel that the charm is deployed from | `string` | n/a | yes |
| <a name="input_config"></a> [config](#input\_config) | Map of the charm configuration options | `map(string)` | `{}` | no |
| <a name="input_constraints"></a> [constraints](#input\_constraints) | String listing constraints for this application | `string` | `"arch=amd64"` | no |
| <a name="input_expose"></a> [expose](#input\_expose) | Make the application publicly available over the network. Requires `external_hostname` to be set in `config`. | `bool` | `false` | no |
| <a name="input_model_uuid"></a> [model\_uuid](#input\_model\_uuid) | ID of the model to deploy to | `string` | n/a | yes |
| <a name="input_resources"></a> [resources](#input\_resources) | The charm's resources i.e., a resource revision number from CharmHub or a custom OCI image resource | `map(string)` | `{}` | no |
| <a name="input_revision"></a> [revision](#input\_revision) | Revision number of the charm | `number` | `null` | no |
| <a name="input_storage_directives"></a> [storage\_directives](#input\_storage\_directives) | Map of storage used by the application, which defaults to 1 GB, allocated by Juju | `map(string)` | `{}` | no |
| <a name="input_units"></a> [units](#input\_units) | Unit count/scale | `number` | `1` | no |

## Outputs

| Name | Description |
|------|-------------|
| <a name="output_application"></a> [application](#output\_application) | The deployed traefik-k8s application. |
| <a name="output_provides"></a> [provides](#output\_provides) | Map of the provides endpoints exposed by the charm. |
| <a name="output_requires"></a> [requires](#output\_requires) | Map of the requires endpoints consumed by the charm. |
<!-- END_TF_DOCS -->

### Exposing the application

Set `expose = true` together with the charm's `external_hostname` to mark the application as publicly available over the network:

```hcl
module "traefik" {
  # ...
  expose = true
  config = { external_hostname = "<hostname>" }
}
```

Juju refuses to expose a Kubernetes (container) application unless `juju-external-hostname` is set, so the module derives `juju-external-hostname` from `external_hostname` automatically. Because of this, setting `expose = true` without `external_hostname` in `config` is rejected at plan time by a variable validation rule, instead of failing later when Juju rejects the apply. This mirrors the pattern used by the [IS COS Terraform module](https://github.com/canonical/is-terraform-modules/blob/main/juju/applications/cos/traefik.tf).

Per-CIDR / per-endpoint / per-space restrictions are intentionally not supported: the traefik-k8s charm manages its own Kubernetes `LoadBalancer` Service and does not honour Juju's expose restrictions, so they would have no effect. To restrict who can reach Traefik, use the charm's `loadbalancer_annotations` config instead.
