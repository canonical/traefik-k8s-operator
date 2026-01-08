---
myst:
  html_meta:
    "description lang=en": "The Traefik charm tutorial that walks a user through TLS termination using a local root-ca."
---

(tutorial_tls_termination_using_a_local_ca)=

# TLS termination using a local CA

## Introduction

By the end of this tutorial you will have several apps deployed, that you could `curl` using an ingress HTTPS URL. For simplicity, in this tutorial we will rely on a self-signed certificate issued by a stand-in local CA.

```{mermaid}
flowchart LR

subgraph Target cluster
  rootca["self-signed-certificates"] ---|tls-certificates| trfk
  trfk[Traefik] ---|ingress-per-app| alertmanager
  trfk[Traefik] ---|ingress-per-unit| prometheus
  trfk[Traefik] ---|traefik-route| grafana

end

curl -.-|via external_hostname| trfk
```

```{note}
This tutorial assumes you have a Juju controller bootstrapped on a MicroK8s cloud that is ready to use. A typical setup using [snaps](https://snapcraft.io/) can be found in the {ref}`Juju docs <juju:set-things-up>`. Follow the instructions there to install Juju and MicroK8s.
```

## Configure MicroK8s

Follow the instructions under the "[Configure MicroK8s](https://discourse.charmhub.io/t/getting-started-on-microk8s/5199)" section to set up MicroK8s with metallb.

## Deploy the apps

Now, we will deploy Traefik, self-signed-certificates (to function as a root CA), and Alertmanager, Prometheus, and Grafana (apps that take an ingress relation).

First, create a new model:

```bash
juju add-model tls-demo
```

Next, save the following bundle as `tls-demo.yaml`:

```yaml
---
bundle: kubernetes
name: traefik-tls-demo

applications:
  traefik:
    charm: 'traefik-k8s'
    scale: 1
    trust: true
    channel: 'edge'
    options:
      external_hostname: 'demo.local'
  alertmanager:
    charm: 'alertmanager-k8s'
    scale: 1
    trust: true
    channel: 'edge'
  prometheus:
    charm: 'prometheus-k8s'
    scale: 1
    trust: true
    channel: 'edge'
  grafana:
    charm: 'grafana-k8s'
    scale: 1
    trust: true
    channel: 'edge'
  ca:
    charm: 'self-signed-certificates'
    scale: 1
    channel: 'edge'

relations:
- [traefik:ingress-per-unit, prometheus:ingress]
- [traefik:traefik-route, grafana:ingress]
- [traefik:ingress, alertmanager:ingress]
- [traefik:certificates, ca:certificates]
```

Finally, deploy the local bundle:

```bash
juju deploy --trust ./tls-demo.yaml
```

## Reach an application's endpoint with ingress

```{note}
By default, the Traefik charm sets up Traefik in a way that allows both HTTP and HTTPS access.
To force HTTPS redirect, see {ref}`Force HTTPS redirect <how_to_force_https_redirect>`.
```

### HTTP

First, obtain the ingress URL by using a Traefik action:

```
juju run traefik/0 show-proxied-endpoints
```

The terminal output should look something like:

```{terminal}
:output-only:

Running operation 5 with 1 task
  - task 6 on unit-traefik-0

Waiting for task 6...
proxied-endpoints: '{
  "prometheus/0": {"url": "http://demo.local:80/tls-demo-prometheus-0"},
  "alertmanager": {"url": "http://demo.local:80/tls-demo-alertmanager"}
}'
```

Now let's obtain Traefik's IP:

```bash
TRAEFIK_IP=$(\
  juju status --format json traefik \
  | jq -r ".applications.traefik.address"\
)
```

Now, use the ingress URL with the application's API HTTP endpoint:

```{terminal}
curl --resolve "demo.local:80:$TRAEFIK_IP" \
  http://demo.local:80/tls-demo-alertmanager/-/ready

OK
```

```{terminal}
curl --resolve "demo.local:80:$TRAEFIK_IP" \
  http://demo.local:80/tls-demo-prometheus-0/-/ready

Prometheus Server is Ready.
```

### HTTPS

Save the certificate locally:

```bash
# TODO avoid literal indexing
juju show-unit --format json traefik/0 \
  | jq -r '."traefik/0"."relation-info"[3]."application-data".certificates' \
  | jq -r '.[1].certificate' \
  > /tmp/local.cert
```

Save Traefik's IP:

```bash
TRAEFIK_IP=$(\
  juju status --format json traefik \
  | jq -r ".applications.traefik.address"\
)
```

Curl the endpoint:

```bash
curl --resolve demo.local:443:$TRAEFIK_IP \
     --fail-with-body \
     --capath /tmp \
     --cacert /tmp/local.cert \
     https://demo.local/tls-demo-alertmanager/-/ready
```

This should return:

```{terminal}
:output-only:

OK
```

