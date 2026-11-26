(how_to_troubleshoot_reachability)=

# How to troubleshoot reachability

After integrating Traefik to your charm, you may encounter reachability errors such as:

- Internal server error
- 404 page not found

## Overview

These errors usually mean that Traefik cannot reach your workload, or cannot serve it at the URL
you expect. This guide goes through the most common causes, in this order:

1. {ref}`The workload is correctly exposed <reachability_exposed>`
2. {ref}`The ingress path prefix is handled correctly <reachability_prefix>`
3. {ref}`The workload's certificate has the correct SAN DNS <reachability_san>`
4. {ref}`Traefik trusts the CA that signed the workload's certificate <reachability_ca>`
5. {ref}`Inspect Traefik's log <reachability_logs>`

Steps 3 and 4 apply only if your workload serves HTTPS. If you develop the charm, see
{ref}`how_to_integrate` for how to make your workload reachable behind Traefik. If none of these
steps help, see {ref}`reachability_getting_help`.

(reachability_exposed)=

## Workload is correctly exposed

`juju ssh` into the charm container and run `ss -tulpn`. Find your app's port in the list and make sure it is not bound to a particular IP, e.g. 

```
Local Address:Port
            *:3200
            *:9096
```

Also make sure Kubernetes has your ports listed as ClusterIP, for example:

```{terminal}
kubectl -n welcome-k8s get svc         

NAME    TYPE        CLUSTER-IP       EXTERNAL-IP   PORT(S)                                                   AGE
tempo   ClusterIP   10.152.183.237   <none>        3200/TCP,4317/TCP,4318/TCP,9411/TCP,14268/TCP,14250/TCP   30m
```

If the workload listens only on `127.0.0.1`, or its port is missing from the Kubernetes service,
Traefik cannot reach it. This is a problem in the charm that provides the workload, not in
Traefik: report it to the charm's maintainers, and see {ref}`how_to_integrate` if you maintain it.

(reachability_prefix)=

## Ingress path prefix is handled correctly

By default, Traefik uses deterministic paths to all proxied endpoints, such as `http://<traefik ip>/model_name-app_name`.

A `404 page not found` or broken links and assets usually mean that the workload doesn't know
about this prefix. Check that the workload serves under the prefix, or that the charm asks Traefik
to strip it:

```bash
curl -i http://<traefik ip>/model_name-app_name/
```

If you don't maintain the charm, report the problem to its maintainers. If you do, either
configure the workload with the prefix or set the `strip_prefix` argument of the ingress
library. See {ref}`how_to_integrate`.

(reachability_san)=

## Workload's certificate has the correct SAN DNS

To avoid using `insecureSkipVerify` in Traefik configuration, the URL specified in the Traefik configuration must match the DNS in the certificate.

Shell into the Traefik workload container to confirm:

```{terminal}
juju ssh --container traefik trfk/0 bash

root@trfk-0:/# cat /opt/traefik/juju/juju_ingress_ingress_48_am.yaml | grep url
        - url: https://am-0.am-endpoints.welcome-k8s.svc.cluster.local:9093
root@trfk-0:/# echo | openssl s_client -showcerts -connect am-0.am-endpoints.welcome-k8s.svc.cluster.local:9093 | openssl x509 -text | grep DNS
                DNS:am-0.am-endpoints.welcome-k8s.svc.cluster.local
```

If the SAN doesn't match, the workload's certificate must be re-issued with the right name. Check
that the workload's charm requests a certificate for the hostname Traefik uses, and that the
certificate provider is integrated with it. Ask the charm's maintainers if it doesn't.

(reachability_ca)=

## Traefik trusts the CA that signed the workload's certificate

To avoid using `insecureSkipVerify` in Traefik configuration, Traefik must trust the CA that signed the proxied app's certificate.

Shell into the Traefik workload container to confirm:

```{terminal}
juju ssh --container traefik trfk/0 bash

root@trfk-0:/# cat /opt/traefik/juju/juju_ingress_ingress_48_am.yaml | grep -E "url|cert"
      - /opt/traefik/juju/ca.cert
        - url: https://am-0.am-endpoints.welcome-k8s.svc.cluster.local:9093
root@trfk-0:/# curl --capath /opt/traefik/juju \
    --cacert /opt/traefik/juju/ca.cert \
    https://am-0.am-endpoints.welcome-k8s.svc.cluster.local:9093/welcome-k8s-am/-/ready
OK
```

If the request fails with a certificate verification error, Traefik doesn't trust the CA. DNS, connectivity, or HTTP errors indicate a different problem; inspect the `curl` error and Traefik log before changing the certificate integration. Integrate Traefik with the same certificate provider as the workload, or provide the CA to Traefik with the `receive-ca-cert` relation. See {ref}`explanation_tls` if you need background on how Traefik handles TLS.

(reachability_logs)=

## Inspect Traefik's log

Make sure Traefik is running.

```{terminal}
juju ssh --container traefik trfk/0 /charm/bin/pebble changes traefik

ID   Status  Spawn               Ready               Summary
1    Done    today at 13:20 UTC  today at 13:20 UTC  Replan service "traefik"

juju ssh --container traefik trfk/0 /charm/bin/pebble tasks 1        

Status  Spawn               Ready               Summary
Done    today at 13:20 UTC  today at 13:20 UTC  Start service "traefik"
```

Look at the Traefik log as you add or remove relations:

```
kubectl -n welcome-k8s logs pods/trfk-0 -c traefik -f
```

(reachability_getting_help)=

## Getting help

If the problem persists,
[file an issue](https://github.com/canonical/traefik-k8s-operator/issues) or ask for help on the
[Matrix chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com). Include the output of
`juju status`, the relevant Traefik logs and the contents of the Traefik configuration file for
your workload (`/opt/traefik/juju/juju_ingress_*.yaml`).
