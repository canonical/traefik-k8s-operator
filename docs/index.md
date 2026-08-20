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

The charm provides a managed ingress entry point for applications running in your Juju model,
handling deployment, routing, configuration, TLS integration, and operational tasks specific to
Traefik. It can be composed with other operators to deliver complex applications and services.

The charm offers different kinds of ingress:

- **Ingress for each app**: This is the typical use case. The related app has only one ingress URL like `/mymodel-myapp`, and Traefik will load-balance in a round-robin fashion across all units.
- **Ingress for each unit**: Each unit of the related app obtains its own ingress URL, like `/mymodel-myapp-0`.
- **Traefik route**: This is a means to provide a fully custom ingress configuration to Traefik.

```{note} 
Ingress is a purely in-model concern. Traefik will happily cross-model relate with your remote ingress requirers, but will be unable to actually route to them. [This is a known issue.](https://github.com/canonical/operator/issues/970) 
```

## In this documentation

```{list-table}
:header-rows: 1
:widths: 10 25

* -
  -
* - **Get started**
  - {ref}`Guided tutorial <tutorial_basic_deployment>`
* - **Deployment**
  - {ref}`Configure TLS termination using a local CA <how_to_tls_termination_using_a_local_ca>`
* - **Operations**
  - {ref}`Troubleshoot reachability <how_to_troubleshoot_reachability>` | {ref}`Troubleshoot Gateway Address Unavailable <how_to_troubleshoot_gateway_address_unavailable>` | {ref}`Upgrade <how_to_upgrade>`
* - **Ingress and interfaces**
  - {ref}`Integrate your charm with Traefik <how_to_integrate>` | {ref}`Ingress-related relations <reference_ingress_integrations>`
* - **Design**
  - {ref}`Charm architecture <reference_charm_architecture>`
* - **Security**
  - {ref}`Security overview <explanation_security>` | {ref}`Enable BasicAuth <how_to_enable_basicauth>` | {ref}`Cryptographic documentation <reference_cryptographic_documentation_for_cos_lite_charms>`
```

## How this documentation is organized

This documentation uses the [Diátaxis documentation structure](https://diataxis.fr/).

- The {ref}`Tutorial <tutorial_index>` takes you step-by-step through a basic Traefik deployment and shows how to expose a workload through ingress.
- {ref}`How-to guides <how_to_index>` cover practical tasks for integrating applications, securing ingress, troubleshooting issues, upgrading, and contributing to the project.
- {ref}`Reference <reference_index>` provides technical details on charm architecture, ingress-related relations, and cryptographic considerations.
- {ref}`Explanation <explanation_index>` gives background and context for security-related topics.
- {ref}`Release notes <release_notes_index>` track stable charm revisions, including new features, bug fixes, and compatibility notes.

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
explanation/index.md
Release notes <release-notes/index.md>
```
