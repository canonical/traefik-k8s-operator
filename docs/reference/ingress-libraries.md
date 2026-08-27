---
myst:
  html_meta:
    "description lang=en": "Reference material for the ingress charm libraries provided by Traefik."
---

(reference_ingress_libraries)=

# Ingress library reference

This page covers selected parameters and behaviour of the ingress charm libraries provided by
Traefik. For full API documentation, visit the Charmhub library pages:

- [`ingress`](https://charmhub.io/traefik-k8s/libraries/ingress)
- [`ingress_per_unit`](https://charmhub.io/traefik-k8s/libraries/ingress_per_unit)
- [`traefik_route`](https://charmhub.io/traefik-k8s/libraries/traefik_route)

## The `strip_prefix` parameter

`IngressPerAppRequirer` (and `IngressPerUnitRequirer`) accept a `strip_prefix: bool = False`
constructor argument. In `path` routing mode (the default), Traefik always generates a
model/app-unique path prefix for your application (e.g. `/model_name-app_name`), and the
ingress URL handed back to clients always includes that prefix — `strip_prefix` does **not**
change the externally-visible URL.

What `strip_prefix=True` actually does is add a Traefik `stripPrefix` middleware that removes
the prefix only from the request Traefik forwards on to your workload, so your application sees
the request as if it had been made against `/` instead of `/model_name-app_name/...`.

`strip_prefix` only has an effect in `path` routing mode. In `subdomain` routing mode there is
no path prefix to strip, so the option is a no-op.

## The `traefik-route` interface: things to keep in mind

### Automatic TLS twin router (default `raw=False` mode)

By default, Traefik automatically generates a TLS-enabled twin of every HTTP router you declare
(named `<router>-tls`) and attaches it to the `websecure` entrypoint. Do not declare your own
`-tls`-suffixed routers or `tls` blocks in your submitted config unless you opt out of this
behaviour by setting `raw=True`. Attach your own HTTP router to the `web` entrypoint; Traefik
will not rewrite your router's `entryPoints` for you.

### Certificate resolvers

This charm does not request certificates from an ACME server. It only uses certificates that
are supplied to it via the `certificates` relation or the `tls-*` config options. Do not set
`certResolver` in your router's `tls` block; that option is only valid when Traefik itself is
obtaining certificates via ACME.

### Unique router and service names

If more than one application can relate to the same Traefik instance over `traefik-route`,
ensure your router and service names are unique across relations. Traefik merges all submitted
configurations together, so a name collision will cause one relation's config to silently
overwrite another.
