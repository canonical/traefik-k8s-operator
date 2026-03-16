(explanation_security)=

# Security overview

This document outlines common risks and possible best practices for the HTTP request Lego provider charm. It focuses on configurations and protections available through the charm itself.

## Risks

The following items include descriptions of the risks, their corresponding best practices for mitigation, as well as links to related documentation and configuration guidelines.

### Security vulnerabilities

Running HTTP request Lego provider with one or more weaknesses that can be exploited by attackers.

#### Best practices

- Keep the Juju and the charm updated. See more about Juju updates in the [documentation](https://documentation.ubuntu.com/juju/latest/explanation/juju-security/index.html#regular-updates-and-patches).

### Unencrypted traffic

If Traefik serves HTTP, the traffic between Traefik and the clients will be unencrypted, risking eavesdropping and tampering.

#### Best practices

- Always enable HTTPS by setting the [`tls-ca`](https://charmhub.io/traefik-k8s/configurations#tls-ca), [`tls-cert`](https://charmhub.io/traefik-k8s/configurations#tls-cert)
and [`tls-key`](https://charmhub.io/traefik-k8s/configurations#tls-key) configuration options.

