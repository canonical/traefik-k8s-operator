(how_to_integrate)=

# How to integrate your charm to Traefik

Traefik provides ingress to other charmed applications. If a charm integrates with Traefik, it can delegate the responsibility of providing ingress to Traefik.

The Traefik charm supports three ways for a charm to obtain ingress:

- [`ingress`](https://github.com/canonical/charm-relation-interfaces/tree/main/interfaces/ingress/v2#readme):
  each charmed application requests a single, cluster-unique URL for ingress. You can choose
  between a domain-name-based URL (`your.parameters.domain.com`) and a path-based URL
  (`domain.com\your\parameters`).
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

`IngressPerAppRequirer` (and `IngressPerUnitRequirer`) accept a `strip_prefix: bool = False`
constructor argument. In `path` routing mode (the default), Traefik always generates a
model/app-unique path prefix for your application (e.g. `/model_name-app_name`), and the
ingress URL handed back to clients always includes that prefix - `strip_prefix` does **not**
change the externally-visible URL.

What `strip_prefix=True` actually does is add a Traefik `stripPrefix` middleware that removes
the prefix only from the request Traefik forwards on to your workload, so your application sees
the request as if it had been made against `/` instead of `/model_name-app_name/...`.

`strip_prefix` only has an effect in `path` routing mode. In `subdomain` routing mode there is
  no path prefix to strip, so the option is a no-op.

### Updating the ingress request later on

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
Use whichever of the two APIs: constructor arguments, or `provide_ingress_requirements`.
Most charms only need one or the other, not both.
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
optionally static) configuration, which Traefik merges into its own configuration. A few things
to keep in mind when using this interface (see the
[`traefik_route` library docstring](https://charmhub.io/traefik-k8s/libraries/traefik_route) for
full usage examples):

- By default, Traefik automatically generates a TLS-enabled twin of every router you declare and
  attaches it to its own `websecure` entrypoint; attach your own router to the `web` entrypoint.
  You should not declare your own `-tls`-suffixed routers or `tls` blocks unless you opt out of
  this via the library's `raw=True` mode.
- Traefik in this charm does not request certificates from an ACME server by itself. It only
  uses certificates that are given to it by the charm. Because of that, your router `tls`
  settings should not include `certResolver`, since that option is only for setups where Traefik
  is directly obtaining certificates for you.
- If more than one instance of your charm (or more than one application) can relate to the same
  Traefik over `traefik-route`, ensure your router/service names are unique across relations to
  avoid collisions when Traefik merges everyone's configuration together.

