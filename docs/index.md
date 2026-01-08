---
myst:
  html_meta:
    "description lang=en": "A Juju charm deploying and managing Traefik on Kubernetes."
---
(index)=

# Traefik operator

A [Juju](https://juju.is/) {ref}`charm <juju:charm>` deploying and managing [Traefik], an ingress
integrator and reverse proxy for Kubernetes. It is an essential part of the [COS Lite bundle]
and is intended to be used together with certificates provider over the `tls-certificates` interface.

This operator handles instantiation, scaling, configuration, and Day 2 operations specific to Traefik.
The charm drives the Traefik application, and it can be composed with other operators to deliver a complex application or service.

The charm offers different kinds of ingress:

- **Ingress per app**: This is the typical use case. The related app has only one ingress URL like `/mymodel-myapp`, and Traefik will load-balance in a round-robin fashion across all units.
- **Ingress per unit**: Each unit of the related app obtains its own ingress URL, like `/mymodel-myapp-0`.
- **Traefik route**: This is a means to provide a fully custom ingress configuration to Traefik.

```{note} 
Ingress is a purely in-model concern. Traefik will happily cross-model relate with your remote ingress requirers, but will be unable to actually route to them. [This is a known issue.](https://github.com/canonical/operator/issues/970) 
```

## In this documentation

| | |
|-|-|
| {ref}`Tutorial <tutorial_index>`</br>  Get started - a hands-on introduction for new users deploying the charmed operator.</br> | {ref}`How-to guides <how_to_index>`</br> Step-by-step guides covering key operations and common tasks |
| {ref}`Reference <reference_index>`</br> Technical information - specifications, APIs, architecture    |        |

## Contributing to this documentation

Documentation is an important part of this project, and we take the same open-source approach to the documentation as the code. As such, we welcome community contributions, suggestions, and constructive feedback on our documentation. See {ref}`How to contribute <how_to_contribute>` for more information.

If there's a particular area of documentation that you'd like to see that's missing, please [file a bug](https://github.com/canonical/traefik-k8s-operator/issues).

## Project and community

The Traefik operator is part of the Canonical Observability Stack. It’s an open source project that warmly welcomes community projects, contributions, suggestions, fixes and constructive feedback.

* [Read our Code of conduct](https://ubuntu.com/community/code-of-conduct)
* [Join the Discourse community forum](https://discourse.charmhub.io/tag/traefik)
* [Join the Matrix community chat](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
* [Contribute](how_to_contribute)

Thinking about using the Canonical Observability Stack for your next project? [Get in touch!](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)

[Traefik]: https://traefik.io/
[COS Lite bundle]: https://charmhub.io/cos-lite


```{toctree}
:hidden:
tutorial/index.md
how-to/index.md
reference/index.md
changelog.md
```
