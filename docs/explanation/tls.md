---
myst:
  html_meta:
    "description lang=en": "Learn how TLS is configured for upstream and downstream traffic in the Traefik charm."
---

(explanation_tls)=

# How TLS works in the Traefik charm

TLS in the Traefik charm is split into two independent segments: **upstream** traffic (between
an external client and Traefik) and **downstream** traffic (between Traefik and the application
requiring ingress). They are configured differently, are not required to be either both on or
both off, and use different certificates.

```{mermaid}
flowchart LR

client((client)) -->|"upstream (external)"| trfk[Traefik]
trfk -->|"downstream (cluster-internal)"| app[App requiring ingress]
```

## Upstream TLS: client to Traefik

Upstream TLS termination is configured on Traefik as a whole, on an **all-or-nothing** basis:
either every route Traefik serves gets HTTPS, or none of them do. There is no per-route toggle
for upstream TLS.

You can provide Traefik with a certificate in one of two ways:

- Integrate a certificate provider charm (such as `self-signed-certificates`) over the
  `certificates` relation. See {ref}`how_to_tls_termination_using_a_local_ca` for a working
  example.
- Set the `tls-cert`, `tls-key`, and `tls-ca` charm configuration options directly. All three must be
  set together; the charm blocks if only some of them are provided.

Once upstream TLS is enabled, clients that call `https://<external_hostname>/...` need the CA
certificate available to them in order to validate the certificate Traefik presents.

## Downstream TLS: Traefik to the app requiring ingress

Downstream TLS is configured **per application**, independently of upstream TLS. Each requirer
charm sets the `scheme` field on its `ingress`/`ingress-per-app` relation data argument, or the
`scheme` argument to `provide_ingress_requirements`. Allowed values are `http`, `https`, and `h2c`.

- If `scheme=http` (the default), Traefik forwards the request to the application in plain
  text.
- If `scheme=https`, Traefik validates the application's own certificate and encrypts traffic
  between itself and the application. For this validation to work, Traefik needs a CA certificate that lets
  it validate the application's certificate; this is typically supplied via the
  `receive-ca-cert` relation (the `certificate_transfer` interface) from the same certificate
  provider used by the application, or from the `certificates` relation if the same authority
  issues Traefik's own certificate.

## Putting it together

If both segments have TLS enabled, a request flows like this:

1. A client calls `https://traefik.gateway/some-route`.
2. Traefik replies with its own certificate (issued via the `certificates` relation, or via the
   `tls-*` config options).
3. The client verifies the certificate, encrypts the request, and sends it to Traefik.
4. Traefik decrypts the request.
5. Traefik calls `https://some-internal-svc-serving-the-route`.
6. The application replies with its own certificate.
7. Traefik verifies that certificate (using a CA cert it received separately), encrypts the
   request, and sends it to the application.

Because the two segments are configured independently, it is entirely possible to
run with upstream TLS enabled and downstream TLS disabled (external clients get HTTPS, but
in-cluster traffic to the application is plain text), or vice-versa.

```{note}
This TLS model is shared by other Juju ingress providers as well (for example `istio-ingress-k8s`),
since it follows from the shape of the `ingress`/`ingress-per-app` relation interfaces rather than
being specific to Traefik's implementation.
```
