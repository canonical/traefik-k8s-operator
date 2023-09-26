# Traefik Kubernetes Charmed Operator

[![CharmHub Badge](https://charmhub.io/traefik-k8s/badge.svg)](https://charmhub.io/traefik-k8s)
[![Release Edge](https://github.com/canonical/traefik-k8s-operator/actions/workflows/release-edge.yaml/badge.svg)](https://github.com/canonical/traefik-k8s-operator/actions/workflows/release-edge.yaml)
[![Release Libraries](https://github.com/canonical/traefik-k8s-operator/actions/workflows/release-libs.yaml/badge.svg)](https://github.com/canonical/traefik-k8s-operator/actions/workflows/release-libs.yaml)
[![Discourse Status](https://img.shields.io/discourse/status?server=https%3A%2F%2Fdiscourse.charmhub.io&style=flat&label=CharmHub%20Discourse)](https://discourse.charmhub.io)

This [Juju](https://juju.is) charmed operator written with the [Operator Lifecycle Manager Framework](https://juju.is/docs/olm), powering _ingress controller-like_ capabilities on Kubernetes.
By _ingress controller-like_ capabilities, we mean that the Traefik Kubernetes charmed operator exposes Juju applications to the outside of a Kubernetes cluster, **without** relying on the [`ingress` resource](https://kubernetes.io/docs/concepts/services-networking/ingress/) of Kubernetes.
Rather, Traefik is instructed to expose Juju applications by means of relations with them.

## Setup

These instructions assume you will run the charm on [`microk8s`](https://microk8s.io), and rely on a few plugins, specifically:

```sh
sudo snap install microk8s
microk8s enable storage dns
# The following line is required unless you plan to use the `external_hostname` configuration option
microk8s enable metallb 192.168.0.10-192.168.0.100 # You likely want change these IP ranges
```

## Usage

```sh
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=ghcr.io/canonical/traefik:2.10.4
```

## Configurations

* `external_hostname` allows you to specify a host for the URL that Traefik will assume is its externally-visible URL, and that will be used to generate the URLs passed to the proxied applications. Note that this has to be a 'bare' hostname, i.e. no `http` prefix and no `:port` suffix. Neither are configurable at the moment. (see )
  If `external_hostname` is unspecified, Traefik will use the ingress ip of its Kubernetes service, and the charm will go into `WaitingStatus` if it does not discover an ingress IP on its Kubernetes service.
  The [Setup](#setup) section shows how to optionally set up `metallb` with MicroK8s, so that Traefik's Kubernetes service will receive an ingress IP.

* `routing_mode`: structured as an enumeration, that allows you to select how Traefik will generate routes:
  * `path`: Traefik will use its externally-visible url and create a route for the requester that will be structure like:

    ```
    http://<external_hostname>:<port>/<requester_model_name>-<requester_application_name>-<requester-unit-index>
    ```

    For example, an ingress-per-unit provider with `http://foo` external URL, will provide to the unit `my-unit/2` in the `my-model` model the following URL:

    ```
    http://foo/my-model-my-unit-2
    ```

  * `subdomain`: Traefik will use its externally-visible url, based on `external_hostname` or, missing that, the ingress IP, and create a route for the requester that will be structure like:

    ```
    http://<requester_model_name>-<requester_application_name>-<requester-unit-index>.<external_hostname>:<port>/
    ```

    For example, an ingress-per-unit provider with `http://foo:8080` external URL, will provide to the unit `my-unit/2` in the `my-model` model the following URL:

    ```
    http://my-model-my-unit-2.foo:8080
    ```

    **IMPORTANT:** With the `subdomain` routing mode, incoming HTTP requests have the `Host` header set to match one of the routes.
    Considering the example above, incoming requests are expected to have the following HTTP header:

    ```
    Host: my-model-my-unit-2.foo
    ```

## Relations

### Providing ingress proxying

This charmed operator supports two types of proxying:

* `per-app`: This is the "classic" proxying logic of an ingress-controller, load-balancing incoming connections to the various units of the Juju application related via the `ingress` relation by routing over the latter's Kubernetes service.
* `per-unit`: Traefik will have routes to the single pods of the proxied Juju application related to it via the `ingress-per-unit` relation.
  This type of routing, while somewhat unconventional in Kubernetes, is necessary for applications like Prometheus (where each remote-write endpoint needs to be routed to separately) and beneficial to databases, the clients of which can perform client-side load balancing

### Monitoring Traefik itself

The metrics endpoint exposed by Traefik can be scraped by Prometheus over the [`prometheus_scrape` relation interface](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) with:

```sh
juju add-relation traefik-ingress:metrics-endpoint prometheus
```

## Contributing

Please see the [Juju SDK docs](https://juju.is/docs/sdk) for guidelines on enhancements to this charm following best practice guidelines, and [CONTRIBUTING.md](https://github.com/canonical/traefik-k8s-operator/blob/main/CONTRIBUTING.md) for developer guidance.
