---
myst:
  html_meta:
    "description lang=en": "How-to guides covering the entire Traefik charm operations lifecycle."
---

(how_to_index)=

# How-to guides

Manage the full operations lifecycle of the Traefik charm, from integrating applications through
production maintenance. Each guide assumes that you've already deployed the charm with Juju.

## Integrations and security

Once you've set up the charm, you can use Traefik's ingress and authentication features to route
traffic to your applications and protect exposed endpoints.

* {ref}`Integrate with traefik and traefik-route <how_to_integrate>`
* {ref}`Configure TLS termination using a local CA <how_to_tls_termination_using_a_local_ca>`
* {ref}`Enable BasicAuth <how_to_enable_basicauth>`

## Troubleshooting

This section contains how-to guides for troubleshooting actions during normal operation.

* {ref}`Troubleshoot "Gateway Address Unavailable" <how_to_troubleshoot_gateway_address_unavailable>`
* {ref}`Troubleshoot reachability <how_to_troubleshoot_reachability>`

## Maintenance and development

Upgrades and community contributions ensure the Traefik charm stays current and benefits from ongoing improvements.

* {ref}`Upgrade <how_to_upgrade>`
* {ref}`Contribute <how_to_contribute>`


```{toctree}
:hidden:

Enable BasicAuth <enable-basicauth>
Integrate <integrate>
Configure TLS termination using a local CA <tls-termination-using-a-local-ca>
Troubleshoot "Gateway Address Unavailable" <troubleshoot-gateway-address-unavailable>
Troubleshoot reachability <troubleshoot-reachability>
Upgrade <upgrade>
Contribute <contribute>
```
