# Contributing

## Development environment

### Prerequisites

Make sure the following software and tools are installed in the development
environment.

- `microk8s`
- `juju`
- `terraform`

### Prepare Development Environment

Install Microk8s:

```console
sudo snap install microk8s --channel=1.27-strict/stable
sudo usermod -a -G snap_microk8s $USER
newgrp snap_microk8s
```

Enable `storage` plugin for Microk8s:

```console
sudo microk8s enable hostpath-storage
```

Install Juju:

```console
sudo snap install juju --channel=3.1/stable
```

Install Terraform:

```console
sudo snap install --classic terraform
```

Bootstrap the Juju Controller using Microk8s:

```console
juju bootstrap microk8s
```

Add a Juju model:

```console
juju add model <model-name>
````

### Terraform provider

The Terraform module uses the Juju provider to provision Juju resources. Please refer to the [Juju provider documentation](https://registry.terraform.io/providers/juju/juju/latest/docs) for more information.

A Terraform working directory needs to be initialized at the beginning.

Initialise the provider:

```console
terraform init
```

## Testing

Terraform CLI provides various ways to do formatting and validation.

Formats to a canonical format and style:

```console
terraform fmt
```

Check the syntactical validation:

```console
terraform validate
```

Preview the changes:

```console
terraform plan
```
