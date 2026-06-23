(how_to_integrate)=

# How to integrate your charm to Traefik

Traefik provides ingress to other charmed applications. If a charm integrates with Traefik, it can delegate the responsibility of providing ingress to Traefik.

See {ref}`Ingress-related relations <reference_ingress_integrations>` for more details on the Traefik charm ingress-related relations.

## Add ingress to your charm

Traefik owns two charm libraries to facilitate integrating with it over `ingress` and `ingress_per_unit`.
At the time of writing, the most recent `ingress` version is v2. You can verify what the
latest version for the libraries is by visiting the documentation pages on Charmhub:

- [`ingress`](https://charmhub.io/traefik-k8s/libraries/ingress)
- [`ingress_per_unit`](https://charmhub.io/traefik-k8s/libraries/ingress_per_unit)

The following steps assume we want to use `ingress`. Using `ingress_per_unit` is very similar, but the difference is `ingress_per_unit` provides ingress for each unit of the charm. An important feature is that `ingress_per_unit` supports listening for ingress changes for all units of the charm, which is often useful for the leader unit to monitor the ingress status of the entire application. See the documentation page for details on this.

### Add `ingress` to your charm

First, fetch the latest `ingress` library:

```
charmcraft fetch-lib charms.traefik_k8s.v2.ingress
```

This will download `lib/charms/traefik_k8s/v2/ingress.py`.
The simplest way to use the library is to instantiate the `IngressPerAppRequirer` object from your charm's constructor.
You can immediately pass to it the host and port of the server you want ingress (useful if they are static),
or you can defer that decision to a later moment by using the `IngressPerAppRequirer.provide_ingress_requirements` API.

```python
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer, IngressReadyEvent

... # your charm's __init__(self, ...):
        self.ingress = IngressPerAppRequirer(self, host="foo.bar", port=80)
        self.framework.observe(self.ingress.ready, self._on_ingress_ready)
        self.framework.observe(self.ingress.revoked, self._on_ingress_revoked)

    def _on_ingress_ready(self, event: IngressPerAppReadyEvent):
        self.unit.status = ops.ActiveStatus(f"I have ingress at {event.url}!")

    def _on_ingress_revoked(self, _):
        self.unit.status = ops.WaitingStatus(f"I have lost my ingress URL!")

    def _foo(self):
        self.ingress.provide_ingress_requirements(host="foo.com", port=42)
```

Once you have added the `ingress` library the charm would need to be re-packed with `charmcraft pack`.

`IngressPerAppRequirer` will take care of communicating over the `ingress` relation with
`traefik-k8s` and notifying the charm whenever Traefik replies with an ingress URL or
that URL is revoked for some reason (e.g. the cloud admin removed the relation).

## Get the proxied endpoint exposed by Traefik

Deploy your charm alongside `traefik-k8s` and integrate them.

Use the `show-proxied-endpoints` action to get a list of the
endpoints currently exposed by `traefik`, one for each application integrated over
`ingress` and one for each *unit* related over `ingress_per_unit`.

```bash
juju run traefik/0 show-proxied-endpoints
```

These are the URLs at which your workloads are externally accessible.

