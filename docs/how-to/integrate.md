(how_to_integrate)=

# How to integrate your charm to Traefik

Traefik provides ingress to other charmed applications. If a charm integrates with Traefik, it can delegate the responsibility of providing ingress to Traefik.

The Traefik charm supports three ways for a charm to obtain ingress:

- [`ingress`](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2#readme):
  each charmed application requests a single, cluster-unique URL for ingress. You can choose
  between a domain-name-based URL (`your.parameters.domain.com`) and a path-based URL
  (`domain.com/your/parameters`).
- [`ingress-per-unit`](https://github.com/canonical/charm-relation-interfaces/blob/main/interfaces/ingress_per_unit/v0/README.md):
  each charmed application requests a cluster-unique URL for each existing unit. This is ideal
  for applications such as Prometheus, where each remote-write endpoint needs to be routed to
  separately, and database applications who wish to do client-side load-balancing.
- `traefik-route`: the requiring charm submits raw Traefik configuration for full control over
  routing. See {ref}`how_to_integrate_traefik_route` below.

## Add ingress to your charm

Traefik owns two charm libraries to facilitate integrating with it over `ingress` and `ingress_per_unit`.
At the time of writing, the most recent `ingress` version is v2. You can verify what the
latest version for the libraries is by visiting the documentation pages on Charmhub:

- [`ingress`](https://charmhub.io/traefik-k8s/libraries/ingress)
- [`ingress_per_unit`](https://charmhub.io/traefik-k8s/libraries/ingress_per_unit)

The following steps assume we want to use `ingress`. Using `ingress_per_unit` is very similar, but the difference is `ingress_per_unit` provides ingress for each unit of the charm. An important feature is that `ingress_per_unit` supports listening for ingress changes for all units of the charm, which is often useful for the leader unit to monitor the ingress status of the entire application. See the documentation page for more details.

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
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer, IngressPerAppReadyEvent

... # your charm's __init__(self, ...):
        self.ingress = IngressPerAppRequirer(self, host="foo.bar", port=80)
        self.framework.observe(self.ingress.on.ready, self._on_ingress_ready)
        self.framework.observe(self.ingress.on.revoked, self._on_ingress_revoked)

    def _on_ingress_ready(self, event: IngressPerAppReadyEvent):
        self.unit.status = ops.ActiveStatus(f"I have ingress at {event.url}!")

    def _on_ingress_revoked(self, _):
        self.unit.status = ops.WaitingStatus(f"I have lost my ingress URL!")
```

Once you have added the `ingress` library the charm would need to be re-packed with `charmcraft pack`.

`IngressPerAppRequirer` will take care of communicating over the `ingress` relation with
`traefik-k8s` and notifying the charm whenever Traefik replies with an ingress URL or
that URL is revoked for some reason (e.g. the cloud admin removed the relation).

### The `strip_prefix` parameter

Add the `strip_prefix` constructor argument to the `IngressPerAppRequirer` /  `IngressPerUnitRequirer`
object to strip the model path prefix from the request Traefik forwards on to your workload.

For details on the `strip_prefix` parameter and when to use it, see
{ref}`reference_ingress_libraries`.

### Update the ingress request later on

The `host` and `port` passed to the `IngressPerAppRequirer` constructor are only the *initial*
request, used to publish ingress data as soon as the relation is available. If your charm needs
to change what ingress is being requested for after init (for example, because the workload's
port is only known once it's configured), call `provide_ingress_requirements` with the values at
any later point:

```python
    def _on_config_changed(self, _):
        self.ingress.provide_ingress_requirements(host="foo.com", port=42)
```

Each call to `provide_ingress_requirements` overwrites the previous request in the relation
databag; there is only ever a single, current `(host, port)` pair per unit/application.

```{note}
Use only one of the two APIs: either constructor arguments, or `provide_ingress_requirements`.
Using both can lead to inconsistency: if some hooks call `provide_ingress_requirements` and
others do not, hooks that skip the call will leave the previous values in the relation databag,
which may not reflect the charm's current state.
```

## Get the proxied endpoint exposed by Traefik

Deploy your charm alongside `traefik-k8s` and integrate them.

Use the `show-proxied-endpoints` action to get a list of the
endpoints currently exposed by `traefik`, one for each application integrated over
`ingress` and one for each *unit* related over `ingress_per_unit`.

```bash
juju run traefik/0 show-proxied-endpoints
```

These are the URLs at which your workloads are externally accessible.

(how_to_integrate_traefik_route)=

## Use `traefik-route` for raw Traefik configuration

Over the `traefik-route` relation, the requiring charm submits raw Traefik dynamic (and
optionally static) configuration, which Traefik merges into its own configuration. The
[`traefik_route` library page on Charmhub](https://charmhub.io/traefik-k8s/libraries/traefik_route)
contains full usage examples, and {ref}`reference_ingress_libraries` covers the key behaviors
to keep in mind when using this interface.

