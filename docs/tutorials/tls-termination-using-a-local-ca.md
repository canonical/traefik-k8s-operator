(tutorials_tls_termination_using_a_local_ca)=
(tutorials-tls-termination-using-a-local-ca)=
# TLS termination using a local ca

[details=Metadata]
| Key | Value |
| --- | --- |
| Summary | TLS termination using a local root-ca. |
| Categories | deploy-applications |
| Difficulty | 2 |
| Author | [Leon Mintz](mailto:Leon.Mintz@canonical.com) |
[/details]

## Introduction
By the end of this tutorial you will have several apps deployed, that you could `curl` via an ingress https url. For simplicity, in this tutorial we will rely on a self-signed certificate issued by a stand-in local CA.

![image|690x321](upload://bEDCXupV8vq4Z9ku4WvS7uw9art.png) 

([Edit a copy of this diagram](https://mermaid.live/edit#pako:eNp9kU9v1DAQxb-KNed4lT8b0uQMN7hAT9RVNSSTrFXHjuwxtN3sd6-TCCQkxGls6735zfNcoXcDQQejcb_6C3oWn78qq2yIPyaPy0Xco5-IRW9iYPLKCuGd4x4fFAQyowx6sjTInjzrUffIFBQ8Cinlyib89b4K9uPz1mKrD_ceadTPh1bbyVMIciEvcVlWgSY5Z7Q4HdT_W6LVvIrFu5n4QjH828HHRXoXmVaRAo4JsMUlO2ylj94IeZLrT42CXlJgi-bp4gJbnOmYHzKYyc-oh_Rt1w2kIDFnUtCl40AjRsMKlL0laVyGFP3ToNl56EY0gTLAyO7bq-2hYx_pt-ijxjTR_Ee1oIXuCi_QndtTe1e3dX7-0LZN3mTwCl1RtKeyzpu2OtdNXhVlfcvgzbnUoDiVedXelc25rIumquo6A9pH-HJse1_6Tvi-G3bi7R1IeLQM))

```{note}
This tutorial assumes you have a Juju controller bootstrapped on a MicroK8s cloud that is ready to use. A typical setup using [snaps](https://snapcraft.io/) can be found in the [Juju docs](https://juju.is/docs/sdk/dev-setup). Follow the instructions there to install Juju and MicroK8s.
```

## Configure MicroK8s
Follow the instructions under the "[Configure MicroK8s](https://discourse.charmhub.io/t/getting-started-on-microk8s/5199)" section to setup MicroK8s with metallb.

## Deploy the apps
Now, we will deploy traefik, self-signed-certificates (to function as a root CA), and alertmanager, prometheus, and grafana (apps that take an ingress relation).

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

## Reach an application's endpoint via ingress
```{note}
By default, the traefik charm sets up traefik in a way that allows both HTTP and HTTPS access.
To force HTTPS redirect, see "[Force HTTPS redirect](https://discourse.charmhub.io/t/traefik-k8s-docs-force-https-redirect/10810)".
```

### HTTP

First, obtain the ingress url by using a traefik action:
```bash
$ juju run traefik/0 show-proxied-endpoints
Running operation 5 with 1 task
  - task 6 on unit-traefik-0

Waiting for task 6...
proxied-endpoints: '{
  "prometheus/0": {"url": "http://demo.local:80/tls-demo-prometheus-0"},
  "alertmanager": {"url": "http://demo.local:80/tls-demo-alertmanager"}
}'
```
and Traefik's IP:
```bash
$ TRAEFIK_IP=$(\
  juju status --format json traefik \
  | jq -r ".applications.traefik.address"\
)
```

Now, use the ingress URL with the application's API HTTP endpoint:
```bash
$ curl --resolve "demo.local:80:$TRAEFIK_IP" \
   http://demo.local:80/tls-demo-alertmanager/-/ready
OK
$ curl --resolve "demo.local:80:$TRAEFIK_IP" \
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

and save Traefik's IP if you haven't done so already:
```bash
$ TRAEFIK_IP=$(\
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
This should return
```text
OK
```

