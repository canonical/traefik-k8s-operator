---
myst:
  html_meta:
    "description lang=en": "Learn more about the ingress-related relations (integrations) of the Traefik charm."
---

(reference_ingress_integrations)=

# Ingress-related relations

The [Traefik charm](https://charmhub.io/traefik-k8s) provides ingress to
another charmed application through a Juju relation. The idea is that if a charm integrates with
`traefik-k8s` then you can integrate the two applications and your application will
receive the URL at which ingress is made available.

The Traefik charm supports two standardized interfaces:

- [`ingress`](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2#readme) 

  Using this interface, each charmed application can request a single, cluster-unique URL for ingress.
  You can choose between a domain-name-based URL (`your.parameters.domain.com`) and a path-based URL (`domain.com\your\parameters`).
- [`ingress-per-unit`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/ingress_per_unit/v0/README.md)

  Using this interface, each charmed application can request a cluster-unique URL for each
  existing unit. This is ideal for applications such as Prometheus, where each remote-write
  endpoint needs to be routed to separately, and database applications who wish to do
  client-side load-balancing.

## Traefik route charm

The [Traefik route charm](https://charmhub.io/traefik-route-k8s) is a proxy charm that sits
between Traefik and a charm in need of ingress, and is used to provide low-level access to
Traefik configuration, as well as to allow configuration for each relation. 

This charm is ideal for use cases where you need the full expressive power of
[Traefik's routing configuration](https://doc.traefik.io/traefik/routing/overview/),
or if you want to use a single Traefik instance to provide domain-name-based
URL routing to some charms, but path-based URL routing to others.

Over the `traefik-route` relation, the requiring charm submits raw Traefik dynamic (and
optionally static) configuration, which Traefik merges into its own configuration. A few things
to keep in mind when using this interface (see the
[`traefik_route` library docstring](https://charmhub.io/traefik-k8s/libraries/traefik_route) for
full usage examples):

- By default, Traefik automatically generates a TLS-enabled twin of every router you declare and
  attaches it to its own `websecure` entrypoint (your router is attached to `web`); you should
  not declare your own `-tls`-suffixed routers or `tls` blocks unless you opt out of this via the
  library's `raw=True` mode.
- Traefik never connects to a certificate authority capable of automatically generating
  certificates (e.g. via ACME), so a `tls` block - whether yours (in `raw` mode) or
  auto-generated - should never contain `certResolver` or `domains` keys; those only apply when
  Traefik is doing automatic certificate issuance for you.
- If more than one instance of your charm (or more than one application) can relate to the same
  Traefik over `traefik-route`, ensure your router/service names are unique across relations to
  avoid collisions when Traefik merges everyone's configuration together.

See {ref}`How TLS works in the Traefik charm <explanation_tls>` for more on how upstream and
downstream TLS are configured in general.
