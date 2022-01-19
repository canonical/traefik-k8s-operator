# Traefik Ingress Charmed Operator

## Description

This [Juju](https://juju.is) charmed operator written with the [Operator Lifecycle Manager Framework](https://juju.is/docs/olm), powering ingress-like capabilities on Kubernetes.

## OCI Images

```sh
docker build . -t localhost:32000/traefik:v1
```

## Usage

```sh
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=localhost:32000/traefik:v1
```

This charm can be related via the `ingress` relation with the `prometheus-k8s` charm built from the [`istio-gateway-ingress`](https://github.com/canonical/prometheus-k8s-operator/tree/istio-gateway-ingress) branch.

## Relations

TODO: Provide any relations which are provided or required by your charm

## Contributing

<!-- TEMPLATE-TODO: Change this URL to be the full Github path to CONTRIBUTING.md-->

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](./CONTRIBUTING.md) for developer guidance.
