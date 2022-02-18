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
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=docker.io/jnsgruk/traefik:2.6.1
```

## Configurations

* `external_hostname` allows you to specify a host for the URL that Traefik will assume is its externally-visible URL, and that will be used to generate the URLs passed to the proxied applications.
  If unspecified, Traefik will use the ingress ip of its Kubernetes service.
* `routing_mode`: structured as an enumeration, that allows you to select how Traefik will generate routes:
  * `path`: Traefik will use its externally-visible url and create a route for the requester that will be structure like:
    ```
    http://<external_hostname>:<port>/<requester_model_name>-<requester_application_name>-<requester-unit-index>
    ```
    For example, an ingress-per-unit provider with `http://foo` external URL, will provide to the unit `my-unit/2` in the `my-model` model the following URL:
    ```
    http://foo/my-model-my-unit-2
    ```
  * `subdomain`: Traefik will use its externally-visible url, and create a route for the requester that will be structure like:
    ```
    http://<requester_model_name>-<requester_application_name>-<requester-unit-index>.<external_hostname>:<port>/
    ```
    For example, an ingress-per-unit provider with `http://foo:8080` external URL, will provide to the unit `my-unit/2` in the `my-model` model the following URL:
    ```
    http://my-model-my-unit-2.foo:8080
    ```

## Relations

### Providing ingress proxying

This charm can be related via the `ingress-per-unit` relation with the `prometheus-k8s` charm built from the [`ingress` branch](https://github.com/canonical/prometheus-operator/tree/ingress):

```sh
juju add-relation traefik-ingress:ingress-per-unit prometheus-k8s
```

### Monitoring Traefik itself

The metrics endpoint exposed by Traefik can be scraped by Prometheus over the [`prometheus_scrape` relation interface](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) with:

```sh
juju add-relation traefik-ingress:metrics-endpoint prometheus
```

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/traefik-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.
