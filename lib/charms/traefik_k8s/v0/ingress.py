# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Interface Library for ingress.

This library wraps relation endpoints using the `ingress` interface
and provides a Python API for both requesting and providing per-application
ingress, with load-balancing occurring across all units.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`. **Note
that you also need to add the `serialized_data_interface` dependency to your charm's
`requirements.txt`.**

```shell
cd some-charm
charmcraft fetch-lib charms.traefik-k8s.v0.ingress
echo "serialized_data_interface" >> requirements.txt
```

Then, to initialise the library:

```python
# ...
from charms.traefik-k8s.v0.ingress import IngressPerAppRequirer

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress = IngressPerAppRequirer(self, port=80)
    self.framework.observe(self.ingress.on.ready, self._handle_ingress)
    # ...

    def _handle_ingress(self, event):
        log.info("This app's ingress URL: %s", self.ingress.url)
```
"""

import logging
from typing import Optional

from ops.charm import CharmBase, RelationEvent, RelationRole
from ops.framework import EventSource
from ops.model import Relation
from serialized_data_interface import EndpointWrapper
from serialized_data_interface.errors import RelationDataError, UnversionedRelation
from serialized_data_interface.events import EndpointWrapperEvents

# The unique Charmhub library identifier, never change it
LIBID = "DERP"  # can't register a library until the charm is in the store 9_9

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

log = logging.getLogger(__name__)

INGRESS_SCHEMA = {
    "v1": {
        "requires": {
            "app": {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "name": {"type": "string"},
                    "host": {"type": "string"},
                    "port": {"type": "integer"},
                },
                "required": ["model", "name", "host", "port"],
            },
        },
        "provides": {
            "app": {
                "type": "object",
                "properties": {
                    "ingress": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                        },
                    }
                },
                "required": ["ingress"],
            },
        },
    }
}


class IngressPerAppRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more semantically meaningful.
    """


class IngressPerAppProviderEvents(EndpointWrapperEvents):
    """Container for IUP events."""

    request = EventSource(IngressPerAppRequestEvent)


class IngressPerAppProvider(EndpointWrapper):
    """Implementation of the provider of ingress."""

    ROLE = RelationRole.provides.name
    INTERFACE = "ingress"
    SCHEMA = INGRESS_SCHEMA

    on = IngressPerAppProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = None):
        """Constructor for IngressPerAppProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "ingress").
        """
        super().__init__(charm, endpoint)
        self.framework.observe(self.on.ready, self._emit_request_event)

    def _emit_request_event(self, event):
        self.on.request.emit(event.relation)

    def get_request(self, relation: Relation):
        """Get the IngressPerAppRequest for the given Relation."""
        return IngressPerAppRequest(self, relation)

    def is_failed(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified, has an error."""
        if relation is None:
            return any(self.is_failed(relation) for relation in self.relations)
        if super().is_failed(relation):
            return True
        try:
            data = self.unwrap(relation)
        except UnversionedRelation:
            return False

        prev_fields = None

        other_app = relation.app

        new_fields = {
            field: data[other_app][field]
            for field in ("model", "port")
            if field in data[other_app]
        }
        if prev_fields is None:
            prev_fields = new_fields
        if new_fields != prev_fields:
            raise RelationDataMismatchError(relation, other_app)
        return False


class IngressPerAppRequest:
    """A request for per-application ingress."""

    def __init__(self, provider: IngressPerAppProvider, relation: Relation):
        """Construct an IngressRequest."""
        self._provider = provider
        self._relation = relation
        self._data = provider.unwrap(relation)

    @property
    def model(self):
        """The name of the model the request was made from."""
        return self._data[self.app].get("model")

    @property
    def app(self):
        """The remote application."""
        return self._relation.app

    @property
    def app_name(self):
        """The name of the remote app.

        Note: This is not the same as `self.app.name` when using CMR relations,
        since `self.app.name` is replaced by a `remote-{UUID}` pattern.
        """
        return self._relation.app.name

    @property
    def host(self):
        """The hostname to be used to route to the application."""
        return self._data[self.app].get("host")

    @property
    def port(self):
        """The port to be used to route to the application."""
        return self._data[self.app].get("port")

    def respond(self, url: str):
        """Send URL back for the application.

        Note: only the leader can send URLs.
        """
        ingress = self._data[self._provider.charm.app].setdefault("ingress", {})
        ingress["url"] = url
        self._provider.wrap(self._relation, self._data)


class RelationDataMismatchError(RelationDataError):
    """Data from different units do not match where they should."""


class IngressPerAppRequirer(EndpointWrapper):
    """Implementation of the requirer of the ingress relation."""

    ROLE = RelationRole.requires.name
    INTERFACE = "ingress"
    SCHEMA = INGRESS_SCHEMA
    LIMIT = 1

    def __init__(
        self,
        charm: CharmBase,
        endpoint: str = None,
        *,
        host: str = None,
        port: int = None,
    ):
        """Constructor for IngressRequirer.

        The request args can be used to specify the ingress properties when the
        instance is created. If any are set, at least `port` is required, and
        they will be sent to the ingress provider as soon as it is available.
        All request args must be given as keyword args.

        Args:
            charm: the charm that is instantiating the library.
            endpoint: the name of the relation endpoint to bind to (defaults to `ingress`);
                relation must be of interface type `ingress` and have "limit: 1")
            host: Hostname to be used by the ingress provider to address the requiring
                application; if unspecified, the default Kubernetes service name will be used.

        Request Args:
            port: the port of the service
        """
        super().__init__(charm, endpoint)
        if port and charm.unit.is_leader():
            self.auto_data = self._complete_request(host or "", port)

    def _complete_request(self, host: Optional[str], port: int):
        if not host:
            # TODO Make host mandatory?
            host = "{app_name}.{model_name}.svc.cluster.local".format(
                app_name=self.app.name,
                model_name=self.model.name,
            )

        return {
            self.app: {
                "model": self.model.name,
                "name": self.charm.unit.name,
                "host": host,
                "port": port,
            }
        }

    def request(self, *, host: str = None, port: int):
        """Request ingress to this application.

        Args:
            host: Hostname to be used by the ingress provider to address the requirer; if
                unspecified, the Kubernetes service address is used.
            port: the port of the service (required)
        """
        self.wrap(self.relation, self._complete_request(host, port))

    @property
    def relation(self):
        """The established Relation instance, or None."""
        return self.relations[0] if self.relations else None

    @property
    def url(self):
        """The full ingress URL to reach the current unit.

        May return None if the URL isn't available yet.
        """
        if not self.is_ready():
            return {}
        data = self.unwrap(self.relation)
        ingress = data[self.relation.app].get("ingress", {})
        return ingress.get("url")
