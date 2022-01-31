# Traefik Ingress Charmed Operator

## Description

This [Juju](https://juju.is) charmed operator written with the [Operator Lifecycle Manager Framework](https://juju.is/docs/olm), powering ingress-like capabilities on Kubernetes.

## Setup

These instructions assume you will run the charm on [`microk8s`](https://microk8s.io), and rely on a few plugins, specifically:

```sh
sudo snap install microk8s
microk8s enable storage dns registry
microk8s enable metallb 192.168.0.10-192.168.0.100 # You likely wanna change these IP ranges
```

## Usage

```sh
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=localhost:32000/traefik:v1
```

## Relations

### Providing ingress proxying

This charm can be related via the `ingress-unit` relation with the `prometheus-k8s` charm built from the [`johnsca:traefik-ingress-unit`](https://github.com/johnsca/prometheus-operator/tree/traefik-ingress-unit) branch:

```sh
juju add-relation traefik-ingress:ingress-unit prometheus-k8s
```

### Monitoring Traefik itself

The metrics endpoint exposed by Traefik can be scraped by Prometheus over the [`prometheus_scrape` relation interface](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) with:

```sh
juju add-relation traefik-ingress:metrics-endpoint prometheus
```

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/traefik-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.
