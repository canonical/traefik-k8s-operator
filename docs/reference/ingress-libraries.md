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
