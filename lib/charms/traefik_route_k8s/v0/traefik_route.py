#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for traefik_route.

This library wraps relation endpoints for traefik_route. The requirer of this
relation is the traefik-route-k8s charm, or any charm capable of providing
Traefik configuration files. The provider is the traefik-k8s charm, or another
charm willing to consume Traefik configuration files.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.traefik_route_k8s.v0.traefik_route
```

To use the library from the provider side (Traefik):

```yaml
requires:
    traefik_route:
        interface: traefik_route
        limit: 1
```

```python
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteProvider

class TraefikCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.traefik_route = TraefikRouteProvider(self)

    self.framework.observe(
        self.traefik_route.on.ready, self._handle_traefik_route_ready
    )

    def _handle_traefik_route_ready(self, event):
        config: str = self.traefik_route.get_config(event.relation)  # yaml
        # use config to configure Traefik
```

To use the library from the requirer side (TraefikRoute):

```yaml
requires:
    traefik-route:
        interface: traefik_route
        limit: 1
        optional: false
```

```python
# ...
from charms.traefik_route_k8s.v0.traefik_route import TraefikRouteRequirer

class TraefikRouteCharm(CharmBase):
  def __init__(self, *args):
    # ...
    traefik_route = TraefikRouteRequirer(
        self, self.model.relations.get("traefik-route"),
        "traefik-route"
    )
    if traefik_route.is_ready():
        traefik_route.submit_to_traefik(
            config={'my': {'traefik': 'configuration'}}
        )

```
"""
import logging
from typing import Optional

import yaml
from ops.charm import CharmBase, CharmEvents, RelationEvent
from ops.framework import EventSource, Object, StoredState
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "fe2ac43a373949f2bf61383b9f35c83c"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

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
    The TraefikRouteProvider provides api to do this easily.
    """

    on = TraefikRouteProviderEvents()
    _stored = StoredState()

    def __init__(self, charm: CharmBase, relation_name: str = "traefik-route"):
        """Constructor for TraefikRouteProvider.

        Args:
            charm: The charm that is instantiating the instance.
            relation_name: The name of the relation relation_name to bind to
                (defaults to "traefik-route").
        """
        super().__init__(charm, relation_name)
        self._stored.set_default(external_host=None)

        self.charm = charm
        self._relation_name = relation_name

        if self._stored.external_host != charm.external_host:
            self._stored.external_host = charm.external_host
            self._update_requirers_with_external_host()

        self.framework.observe(
            self.charm.on[relation_name].relation_changed, self._on_relation_changed
        )

    def _on_relation_changed(self, event: RelationEvent):
        if self.is_ready(event.relation):
            # todo check data is valid here?
            self.on.ready.emit(event.relation)

    def _update_requirers_with_external_host(self):
        """Ensure that requirers know the external host for Traefik."""
        if not self.charm.unit.is_leader():
            return

        for relation in self.charm.model.relations[self._relation_name]:
            relation.data[self.charm.app]["external_host"] = self._stored.external_host

    @staticmethod
    def is_ready(relation: Relation) -> bool:
        """Whether TraefikRoute is ready on this relation: i.e. the remote app shared the config."""
        return "config" in relation.data[relation.app]

    @staticmethod
    def get_config(relation: Relation) -> Optional[str]:
        """Retrieve the config published by the remote application."""
        # todo validate this config
        return relation.data[relation.app].get("config")


class TraefikRouteRequirer(Object):
    """Wrapper for the requirer side of traefik-route.

    The traefik_route requirer will publish to the application databag an object like:
    {
        'config': <Traefik_config>
    }

    NB: TraefikRouteRequirer does no validation; it assumes that the
    traefik-route-k8s charm will provide valid yaml-encoded config.
    The TraefikRouteRequirer provides api to store this config in the
    application databag.
    """

    on = TraefikRouteRequirerEvents()
    _stored = StoredState()

    def __init__(self, charm: CharmBase, relation: Relation, relation_name: str = "traefik-route"):
        super(TraefikRouteRequirer, self).__init__(charm, relation_name)
        self._stored.set_default(external_host=None)

        self._charm = charm
        self._relation = relation

        self.framework.observe(
            self._charm.on[relation_name].relation_changed, self._on_relation_changed
        )

    @property
    def external_host(self) -> str:
        """Return the external host set by Traefik, if any."""
        return self._stored.external_host or ""

    def _on_relation_changed(self, event: RelationEvent) -> None:
        """Update StoredState with external_host and other information from Traefik."""
        if self._charm.unit.is_leader():
            external_host = event.relation.data[event.app].get("external_host", "")
            self._stored.external_host = external_host or self._stored.external_host
            self.on.ready.emit(event.relation)

    def is_ready(self) -> bool:
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
        app_databag["config"] = yaml.safe_dump(config)
