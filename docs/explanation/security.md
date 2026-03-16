---
myst:
  html_meta:
    "description lang=en": "Learn more about the common security risks and best practices for the Traefik charm."
---

(explanation_security)=

# Security overview

This document outlines common risks and best practices for the Traefik charm. It focuses on configurations and protections available through the charm itself.

## Risks

The following items include descriptions of the risks, their corresponding best practices for mitigation, as well as links to related documentation and configuration guidelines.

### Security vulnerabilities

Running Traefik with one or more weaknesses that can be exploited by attackers.

#### Best practices

- Keep the Juju and the charm updated. See {ref}`how_to_upgrade`, and learn more about Juju updates in the {ref}`documentation <juju:controls-regular-updates>`.

### Unencrypted traffic

If Traefik serves HTTP, the traffic between Traefik and the clients will be unencrypted, risking eavesdropping and tampering.

#### Best practices

- Always enable HTTPS by integrating with a charm providing the [`certificates`](https://charmhub.io/traefik-k8s/integrations#certificates) integration to configure TLS.
- [Force HTTPS redirect](https://documentation.ubuntu.com/traefik-k8s-charm/latest/how-to/force-https-redirect/) unless you need unencrypted traffic to be supported.
- Consider encrypting in-cluster traffic, specially if your cluster is multi-tenant.

### Authentication

The Traefik charm supports both [BasicAuth](https://doc.traefik.io/traefik/reference/routing-configuration/http/middlewares/basicauth/).

#### Best practices

- Consider [enabling BasicAuth](https://documentation.ubuntu.com/traefik-k8s-charm/latest/how-to/enable-basicauth/) if you want access to the backend workloads to be authenticated.
