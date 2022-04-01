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
import json
import logging
from typing import Optional, Dict

import yaml
from ops.charm import CharmBase, RelationEvent, RelationRole, CharmEvents
from ops.framework import EventSource, Object
from ops.model import Relation, Unit

# The unique Charmhub library identifier, never change it
LIBID = ""

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 0

log = logging.getLogger(__name__)


def _deserialize_data(data):
    return json.loads(data)


def _serialize_data(data):
    return json.dumps(data, indent=2)


class TraefikRouteException(RuntimeError):
    """Base class for exceptions raised by TraefikRoute."""


class UnauthorizedError(TraefikRouteException):
    """Raised when the unit needs leadership to perform some action."""


class RouteRequest:
    def __init__(self, relation: Relation):
        _request = relation.data[relation.app]
        self.config = config = _request['config']
        self.rule = config['rule']
        self.ingress = ingress = _deserialize_data(_request['ingress']['data'])
        self.model = ingress['model']
        self.port = ingress['port']
        self._unit_name = ingress['name']
        self._host_name = ingress['name']

    def get_unit_name(self, unit):
        return self._unit_name

    def get_host(self, unit):
        return self._host_name

    def respond(self, unit, url: str):
        pass

class TraefikRouteRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more meaningful.
    """

    def __init__(self, handle, relation, app=None, unit=None):
        super().__init__(handle, relation, app, unit)
        self.request = RouteRequest(relation)


class TraefikRouteIngressReadyEvent(RelationEvent):
    """Event representing a ready state from the traefik charm."""
    def __init__(self, handle, relation, ingress, app=None, unit=None):
        super().__init__(handle, relation, app=app, unit=unit)
        self.ingress = ingress

    def snapshot(self) -> dict:
        """Used by the framework to serialize the event to disk.

        Not meant to be called by charm code.
        """
        snap = super().snapshot()
        snap['ingress'] = self.ingress
        return snap

    def restore(self, snapshot: dict) -> None:
        """Used by the framework to deserialize the event from disk.

        Not meant to be called by charm code.
        """
        self.ingress = snapshot.pop('ingress')
        super().restore(snapshot)


class TraefikRouteProviderEvents(CharmEvents):
    """Container for TRP events."""
    request = EventSource(TraefikRouteRequestEvent)


class TraefikRouteRequirerEvents(CharmEvents):
    """Container for TRR events."""
    ingress_ready = EventSource(TraefikRouteIngressReadyEvent)


class TraefikRouteProvider(Object):
    """Implementation of the provider of traefik_route.

    This will presumably be owned by a Traefik charm.
    The main idea is that traefik will observe the `request` event and, upon
    receiving it, will
    """
    on = TraefikRouteProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = 'traefik-route'):
        """Constructor for TraefikRouteProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "traefik-route").
        """
        super().__init__(charm, endpoint)
        self.framework.observe(self.on[endpoint].relation_changed,
                               self._on_relation_changed)

    def get_request(self, relation):
        return RouteRequest(relation)

    def is_ready(self, relation):
        """Provider is ready if the remote app has shared any data."""
        # todo validate
        return relation.data.get(relation.app)

    def _on_relation_changed(self, event):
        if self.is_ready(event.relation):
            self.on.request.emit(event.relation)


class TraefikNotReadyError(TraefikRouteException):
    """Raised when TraefikRouteRequirer is asked for a rule which """


class TraefikRouteRequirer(Object):
    """Wrapper for the requirer side of traefik-route.

    traefik_route will publish to the application databag an object like:
    {
        'ingress': {
            'model': 'cos',
            'unit': 'prometheus-k8s/0',
            'host': 'foo/bar',
            'port': 42
        },
        'config': {
            'rule': 'Host(`foo.bar/{{juju_unit}}`)'
        }
    }

    'ingress' is provided by the ingress end-user via ingress_per_unit,
    'config' is provided by the cloud admin via the traefik-route-k8s charm.

    TraefikRouteRequirer does no validation; it assumes that ingress_per_unit
    validates its part of the data, and that the traefik-route-k8s charm will
    do its part by validating the config before this provider is invoked to
    share it with traefik.
    """
    on = TraefikRouteRequirerEvents()

    def __init__(self, charm: CharmBase, endpoint: str = 'traefik-route'):
        super(TraefikRouteRequirer, self).__init__(charm, endpoint)
        self._charm = charm
        self._endpoint = endpoint

        self.framework.observe(charm.on[endpoint].relation_changed,
                               self._on_relation_changed)

    def _on_relation_changed(self, event):
        if ingress := self._get_ingress(event.relation):
            log.info('ingress ready')
            self.on.ingress_ready.emit(event.relation, ingress)

    def _get_ingress(self, relation: Relation):
        data = relation.data[relation.app].get('data')
        if not data:
            return False
        try:
            app_data = json.loads(data)
        except json.JSONDecodeError as e:
            log.error(f"error decoding {data!r} as JSON.")
            return None
        return app_data

    @property
    def relation(self) -> Optional[Relation]:
        """Retrieves the traefik_route relation databag."""
        relations = self._charm.model.relations.get(self._endpoint)
        if relations:
            # Only one traefik_route can be active at once on the requirer's
            # side.
            return relations[0]

    @property
    def proxied_endpoint(self) -> Optional[str]:
        """Return the ingress url provided to this unit by the traefik charm."""
        relation = self.relation
        if not relation or not (app_data := relation.data.get(relation.app)):
            return None
        raw_data = app_data['traefik_route']
        data = _deserialize_data(raw_data)
        endpoint = data.get(self._charm.unit.name, {}).get('url')
        return endpoint

    def relay_ingress_request(self, ingress, config):
        """Relay ingress request of a charm running on `unit` inside `model`.

        Call this when the ingress relation between route charm and
        'ingress end-consumer' charm is ready; aka the end-consumer charm has
        provided the ingress data.
        """
        if not self._charm.unit.is_leader():
            raise UnauthorizedError()

        app_databag = self.relation.data[self._charm.app]
        app_databag['config'] = _serialize_data(config)
        app_databag['ingress'] = _serialize_data(ingress)
