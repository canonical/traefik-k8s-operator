---
myst:
  html_meta:
    "description lang=en": "TBD"
---
(index)=

# Charmed Traefik

<!--Summary-->
`traefik-k8s` is a charm for [Traefik], an ingress integrator and reverse proxy for Kubernetes.
It is an essential part of the [COS Lite bundle].


<!--Description-->
This Charmed Operator handles instantiation, scaling, configuration, and Day 2 operations specific to Traefik.

This operator drives the Traefik application, and it can be composed with other operators to deliver a complex application or service.


<!--Needs-->
The charm offers different kinds of ingress:
- Ingress per app. This is the typical use case. The related app has only one ingress url like `/mymodel-myapp`, and Traefik will load-balance in a round-robin fashion across all units.
- Ingress per unit. Each unit of the related app obtains its own ingress url, like `/mymodel-myapp-0`.
- Traefik route. This is a means to provide a fully custom ingress configuration to Traefik.

```{note} Ingress is a purely in-model concern. Traefik will happily cross-model relate with your remote ingress requirers, but will be unable to actually route to them. [This is a known issue.](https://github.com/canonical/operator/issues/970) ```

<!--Target-->
This charm is:
- part of the COS Lite bundle
- intended to be used together with certificates provider over the `tls-certificates` interface


[Traefik]: https://traefik.io/
[COS Lite bundle]: https://charmhub.io/cos-lite


## In this documentation

| | |
|-|-|
| **Tutorial**</br>  Get started - a hands-on introduction for new users deploying the charmed operator.</br> | **How-to guides**</br> Step-by-step guides covering key operations and common tasks |
| **Explanation**</br> Concepts - discussion and clarification of key topics                   |  **Reference**</br> Technical information - specifications, APIs, architecture    |

## Project and community

The Traefik charmed operator is part of the Canonical Observability Stack. It’s an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

* [Read our Code of conduct](https://ubuntu.com/community/code-of-conduct)
* [Join the Discourse community forum](https://discourse.charmhub.io/tag/traefik)
* [Join the Matrix community chat](https://matrix.to/#/#observability:ubuntu.com)
* [Contribute on GitHub](https://github.com/canonical/traefik-k8s-operator)

Thinking about using the Canonical Observability Stack for your next project? [Get in touch!](https://discourse.charmhub.io/c/charm/41)


```{toctree}
:hidden:
how-to/index.md
reference/index.md
tutorials/index.md
changelog.md
```
