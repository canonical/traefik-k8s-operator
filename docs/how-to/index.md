---
myst:
  html_meta:
    "description lang=en": "How-to guides covering the entire Traefik charm operations lifecycle."
---

(how_to_index)=

# How-to guides

These guides accompany you through the complete Traefik charm operations lifecycle.

## Configuring

Once you've set up the charm, you can take advantage of the built-in features and capabilities to customize the charm based on your specific needs and use cases.

* {ref}`Force HTTPS redirect <how_to_force_https_redirect>`

## Integrating via the `traefik-route` relation

In more advanced cases where the default `ingress` relation is not flexible enough, you can integrate your backend application via the `traefik-route` relation.

* {ref}`Integrate with traefik and traefik-route <how_to_integrate>`

## Troubleshooting

This section contains how-to guides for troubleshooting actions during normal operation.

* {ref}`Troubleshoot "Gateway Address Unavailable" <how_to_troubleshoot_gateway_address_unavailable>`
* {ref}`Troubleshoot reachability <how_to_troubleshoot_reachability>`

## Upgrade

This section contains how-to guides for maintenance actions that you might need to take while operating the charm.

* {ref}`Upgrade <how_to_upgrade>`

## Contributing

This section contains how-to guides for contributing to the project.

* {ref}`Contribute <how_to_contribute>`


```{toctree}
:hidden:

Force HTTPS redirect <force-https-redirect>
Enable BasicAuth <enable-basicauth>
Integrate <integrate>
Troubleshoot "Gateway Address Unavailable" <troubleshoot-gateway-address-unavailable>
Troubleshoot reachability <troubleshoot-reachability>
Upgrade <upgrade>
Contribute <contribute>
```
