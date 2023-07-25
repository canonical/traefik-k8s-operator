## http (am - trfk)
Deploy bundle

```bash
juju deploy --trust ./bundle_1_http.yaml
```

Make sure the "proxied endpoint" has http scheme:

```bash
juju run trfk/0 show-proxied-endpoints --wait 2m
# proxied-endpoints: '{"am": {"url": "http://10.43.8.219/welcome-k8s-am"}}'
```

Curl that endpoint

```bash
curl http://10.43.8.219/welcome-k8s-am/-/ready
# OK%
```

Inspect the server url in the config file:
```shell
juju ssh --container traefik trfk/0 cat /opt/traefik/juju/juju_ingress_ingress_23_am.yaml
# - url: http://am-0.am-endpoints.welcome-k8s.svc.cluster.local:9093
```

## https fqdn (ca - am)
Deploy bundle

```bash
juju deploy --trust ./bundle_2_https_fqdn.yaml
```

Confirm the FQDN is listed in the SANS of the server cert for both am units
```bash
IPADDR0=$(juju status --format json am | jq -r '.applications.am.units."am/0".address')
echo | openssl s_client -connect $IPADDR0:9093 2>/dev/null | openssl x509 -text | grep DNS
# DNS:am-0.am-endpoints.welcome-k8s.svc.cluster.local

IPADDR1=$(juju status --format json am | jq -r '.applications.am.units."am/1".address')
echo | openssl s_client -connect $IPADDR1:9093 2>/dev/null | openssl x509 -text | grep DNS
# DNS:am-1.am-endpoints.welcome-k8s.svc.cluster.local
```

Curl the HTTPS endpoint

```bash
curl -k https://$IPADDR0:9093/-/ready
# OK%

curl -k https://$IPADDR1:9093/-/ready
# OK%
```

## reverse termination (ca - am - trfk)
Deploy bundle

```bash
juju deploy --trust ./bundle_3_reverse_termination.yaml
```

Repeat checks from:
- previous section ("https fqdn (ca - am)")
- "http (am - trfk)" section
  - FIXME: why only one unit displayed in action results?
  - Make sure the scheme is HTTP (NOT HTTPS).
    FIXME: why curling that endpoint gives "404 page not found"?


Curl alertmanager unit IP directly, make sure it responds

```bash
MODEL=$(juju models --format json | jq -r '."current-model"')

IPADDR0=$(juju status --format json am | jq -r '.applications.am.units."am/0".address')
curl -k https://$IPADDR0:9093/$MODEL-am/-/ready
# OK%

IPADDR1=$(juju status --format json am | jq -r '.applications.am.units."am/1".address')
curl -k https://$IPADDR1:9093/$MODEL-am/-/ready
# OK%
```


## TLS termination (am - trfk - ca)
Deploy bundle

```bash
juju deploy --trust ./bundle_4_tls_termination.yaml
```

Repeat checks from:
- "http (am - trfk)"
  - FIXME: RuntimeError: This application did not `publish_url` yet.


Confirm the external hostname is listed in the SANS of the traefik cert
```bash
IPADDR=$(juju status --format json trfk | jq -r '.applications.trfk.units."trfk/0".address')
echo | openssl s_client -connect $IPADDR 2>/dev/null | openssl x509 -text | grep DNS
# DNS:
```

Confirm alertmanager is reachable via ingress URL
```bash
curl -k https://cluster.local/$MODEL-am/-/ready
```


## TLS end-to-end (ca - am - trfk - ca)
Deploy bundle

```bash
juju deploy --trust ./bundle_5_tls_end_to_end.yaml
```

Repeat previous checks.
- FIXME: RuntimeError: This application did not `publish_url` yet.
