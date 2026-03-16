(explanation_security)=

# Security overview

This document outlines common risks and best practices for the Traefik charm. It focuses on configurations and protections available through the charm itself.

## Risks

The following items include descriptions of the risks, their corresponding best practices for mitigation, as well as links to related documentation and configuration guidelines.

### Security vulnerabilities

Running Traefik with one or more weaknesses that can be exploited by attackers.

#### Best practices

- Keep the Juju and the charm updated. See more about Juju updates in the [documentation](https://documentation.ubuntu.com/juju/latest/explanation/juju-security/index.html#regular-updates-and-patches).

### Unencrypted traffic

If Traefik serves HTTP, the traffic between Traefik and the clients will be unencrypted, risking eavesdropping and tampering.

#### Best practices

- Always enable HTTPS by integrating with a charm providing the [`certificates`](https://charmhub.io/traefik-k8s/integrations#certificates) integration to configure TLS.

