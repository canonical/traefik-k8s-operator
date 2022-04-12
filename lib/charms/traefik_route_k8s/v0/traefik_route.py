# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for traefik_route.

This library wraps relation endpoints for traefik_route. The requirer of this
relation is a charm in need of ingress (or a proxy thereof), the
provider is the traefik-k8s charm.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.traefik_route_k8s.v0.traefik_route
```

```yaml
requires:
    traefik_route:
        interface: traefik_route
        limit: 1
```

Then, to initialise the library:

```python
# ...
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress_per_unit = TraefikRouteProvider(self)
    self.traefik_route = TraefikRouteRequirer(self)

    self.framework.observe(
        self.ingress_per_unit.on.request, self.traefik_route.relay
    )
    self.framework.observe(
        self.traefik_route.on.response, self.ingress_per_unit.respond
    )
```
"""
import logging

import yaml
from ops.charm import CharmBase, RelationEvent, CharmEvents
from ops.framework import EventSource, Object
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = ""

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 0

log = logging.getLogger(__name__)


class TraefikRouteException(RuntimeError):
    """Base class for exceptions raised by TraefikRoute."""


class UnauthorizedError(TraefikRouteException):
    """Raised when the unit needs leadership to perform some action."""


class TraefikRouteProviderReadyEvent(RelationEvent):
    """Event emitted when Traefik is ready to provide ingress for a routed unit."""


class TraefikRouteRequirerReadyEvent(RelationEvent):
    """Event emitted when a unit requesting ingress has provided all data Traefik needs."""


class TraefikRouteRequirerEvents(CharmEvents):
    """Container for TraefikRouteRequirer events."""
    ready = EventSource(TraefikRouteRequirerReadyEvent)


class TraefikRouteProviderEvents(CharmEvents):
    """Container for TraefikRouteProvider events."""
    ready = EventSource(TraefikRouteProviderReadyEvent)


class TraefikRouteProvider(Object):
    """Implementation of the provider of traefik_route.

    This will presumably be owned by a Traefik charm.
    The main idea is that Traefik will observe the `ready` event and, upon
    receiving it, will fetch the config from the TraefikRoute's application databag,
    apply it, and update its own app databag to let Route know that the ingress
    is there.
    """
    on = TraefikRouteProviderEvents()

    def __init__(self, charm: CharmBase, relation_name: str = 'traefik-route'):
        """Constructor for TraefikRouteProvider.

        Args:
            charm: The charm that is instantiating the instance.
            relation_name: The name of the relation relation_name to bind to
                (defaults to "traefik-route").
        """
        super().__init__(charm, relation_name)
        self.charm = charm
        self.framework.observe(self.charm.on[relation_name].relation_changed,
                               self._on_relation_changed)

    def _on_relation_changed(self, event: RelationEvent):
        if self.is_ready(event.relation):
            # todo check data is valid here?
            self.on.ready.emit(event.relation)

    @staticmethod
    def is_ready(relation: Relation):
        """Whether TraefikRoute is ready on this relation: i.e. the remote app shared the config."""
        return 'config' in relation.data[relation.app]

    @staticmethod
    def get_config(relation: Relation):
        """Retrieve the config published by the remote application."""
        # todo validate this config
        return relation.data[relation.app]['config']


class TraefikRouteRequirer(Object):
    """Wrapper for the requirer side of traefik-route.

    traefik_route will publish to the application databag an object like:
    {
        'config': <Traefik_config>
    }

    'ingress' is provided by the ingress end-user via ingress_per_unit,
    'config' is provided by the cloud admin via the traefik-route-k8s charm.

    TraefikRouteRequirer does no validation; it assumes that ingress_per_unit
    validates its part of the data, and that the traefik-route-k8s charm will
    do its part by validating the config before this provider is invoked to
    share it with traefik.
    """
    on = TraefikRouteRequirerEvents()

    def __init__(self, charm: CharmBase, relation: Relation,
                 relation_name: str = 'traefik-route'):
        super(TraefikRouteRequirer, self).__init__(charm, relation_name)
        self._charm = charm
        self._relation = relation

    def is_ready(self):
        """Is the TraefikRouteRequirer ready to submit data to Traefik?"""
        return self._relation is not None

    def submit_to_traefik(self, config):
        """Relay an ingress configuration data structure to traefik.

        This will publish to TraefikRoute's traefik-route relation databag
        the config traefik needs to route the units behind this charm.
        """
        if not self._charm.unit.is_leader():
            raise UnauthorizedError()

        app_databag = self._relation.data[self._charm.app]

        # Traefik thrives on yaml, feels pointless to talk json to Route
        app_databag['config'] = yaml.safe_dump(config)
