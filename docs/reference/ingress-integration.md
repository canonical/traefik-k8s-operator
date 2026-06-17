---
myst:
  html_meta:
    "description lang=en": "Learn more about the ingress-related integrations of the Traefik charm."
---

(reference_ingress_integrations)=

# Ingress-related integrations

The [Traefik charm](https://charmhub.io/traefik-k8s) is a charm to provide ingress to
another charmed application 'the Juju way'. The idea is that if a charm integrates with
`traefik-k8s` then you can relate the two applications and your application will
receive the URL at which ingress is made available.

The Traefik charm supports two standardized interfaces:

- [ingress](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2#readme) 

  Using this interface, each charmed application can request a single, cluster-unique URL for ingress.
  You can choose between a domain-name-based URL (`your.parameters.domain.com`) and a path-based URL (`domain.com\your\parameters`).
- [`ingress-per-unit`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/ingress_per_unit/v0/README.md)

  Using this interface, each charmed application can request a cluster-unique URL for each
  existing unit. This is for applications such as Prometheus, where each remote-write
  endpoint needs to be routed to separately, and database applications who wish to do
  client-side load-balancing.

## Traefik route charm

The [Traefik route charm](https://charmhub.io/traefik-route-k8s) is a proxy charm that sits
between Traefik and a charm in need of ingress, and is used to provide low-level access to
Traefik configuration, as well as to allow configuration for each relation. 

Want to have full access to all the expressive power of
[Traefik's routing configuration](https://doc.traefik.io/traefik/routing/overview/)? Want to
have one Traefik instance, and provide domain-name-based URL routing to some charms, but
path-based URL routing to some others? This is how you do it.
