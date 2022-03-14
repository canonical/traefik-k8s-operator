# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for ingress_per_unit.

This library wraps relation endpoints using the `ingress_per_unit` interface
and provides a Python API for both requesting and providing per-unit
ingress.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.
**Note that you also need to add the `serialized_data_interface` dependency to your
charm's `requirements.txt`.**

```shell
cd some-charm
charmcraft fetch-lib charms.traefik_k8s.v0.ingress_per_unit
echo -e "serialized_data_interface\n" >> requirements.txt
```

```yaml
requires:
    ingress:
        interface: ingress_per_unit
        limit: 1
```

Then, to initialise the library:

```python
# ...
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitRequirer

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress_per_unit = IngressPerUnitRequirer(self, port=80)
    # The following event is triggered when the ingress URL to be used
    # by this unit of `SomeCharm` changes or there is no longer an ingress
    # URL available, that is, `self.ingress_per_unit` would return `None`.
    self.framework.observe(
        self.ingress_per_unit.on.ingress_changed, self._handle_ingress_per_unit
    )
    # ...

    def _handle_ingress_per_unit(self, event):
        logger.info("This unit's ingress URL: %s", self.ingress_per_unit.url)
```
"""
import json
import logging
from typing import Optional

from functools import cached_property
import jsonschema
from ops.charm import CharmBase, RelationEvent, RelationRole
from ops.framework import EventSource, Object
from ops.model import Relation, Unit, Application

try:
    from serialized_data_interface import EndpointWrapper
    from serialized_data_interface.errors import RelationDataError
    from serialized_data_interface.events import EndpointWrapperEvents
except ImportError:
    import os

    library_name = os.path.basename(__file__)
    raise ModuleNotFoundError(
        "To use the '{}' library, you must include "
        "the '{}' package in your dependencies".format(library_name, "serialized_data_interface")
    ) from None  # Suppress original ImportError

try:
    # introduced in 3.9
    from functools import cache  # type: ignore
except ImportError:
    from functools import lru_cache

    cache = lru_cache(maxsize=None)

# The unique Charmhub library identifier, never change it
LIBID = "7ef06111da2945ed84f4f5d4eb5b353a"  # can't register a library until the charm is in the store 9_9

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 4

log = logging.getLogger(__name__)
SUPPORTED_VERSIONS_KEY = '_supported_versions'

INGRESS_REQUIRES_UNIT_SCHEMA = {
                "type": "object",
                "properties": {
                    "model": {"type": "string"},
                    "name": {"type": "string"},
                    "host": {"type": "string"},
                    "port": {"type": "integer"},
                },
                "required": ["model", "name", "host", "port"],
            }

INGRESS_PROVIDES_APP_SCHEMA = {
                "type": "object",
                "properties": {
                    "ingress": {
                        "type": "object",
                        "patternProperties": {
                            "": {
                                "type": "object",
                                "properties": {"url": {"type": "string"}},
                                "required": ["url"],
                            }
                        },
                    }
                },
                "required": ["ingress"],
            }


class IngressPerUnitRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more semantically meaningful.
    """


class IngressPerUnitProviderEvents(EndpointWrapperEvents):
    """Container for IUP events."""

    request = EventSource(IngressPerUnitRequestEvent)


def update(databag, data: dict, schema=None):
    for key, value in data:
        databag[key] = value
    if schema:
        pass # todo validation


class IngressPerUnitProvider(Object):
    """Implementation of the provider of ingress_per_unit."""

    on = IngressPerUnitProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = 'ingress-per-unit',
                 auto_data: dict = None):
        """Constructor for IngressPerUnitProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "ingress-per-unit").
        """
        super().__init__(charm, endpoint)
        self.auto_data = auto_data or {}
        self.charm = charm
        self.endpoint = endpoint

        observe = self.framework.observe
        observe(self.on.ready, self._emit_request_event)

        rel_events = charm.on[endpoint]
        observe(rel_events.relation_created, self._handle_relation)
        observe(rel_events.relation_changed, self._handle_relation)
        observe(rel_events.relation_broken, self._handle_relation_broken)
        observe(charm.on.leader_elected, self._handle_upgrade_or_leader)
        observe(charm.on.upgrade_charm, self._handle_upgrade_or_leader)

    @property
    def app(self):
        """Shortcut to self.charm.app."""
        return self.charm.app

    @property
    def unit(self):
        """Shortcut to self.charm.unit."""
        return self.charm.unit

    def _handle_relation(self, event):
        self._send_versions(event.relation)
        if self.is_ready(event.relation):
            self.on.ready.emit(event.relation)
        elif self.is_available(event.relation):
            self.on.available.emit(event.relation)
        elif self.is_failed(event.relation):
            self.on.failed.emit(event.relation)

    def _handle_relation_broken(self, event):
        self.on.broken.emit(event.relation)

    def _handle_upgrade_or_leader(self, event):
        for relation in self.relations:
            self._send_versions(relation)

    def _send_versions(self, relation: Relation):
        if self.unit.is_leader():
            relation.data[self.app][SUPPORTED_VERSIONS_KEY] = '- v1'

    def _emit_request_event(self, event):
        self.on.request.emit(event.relation)

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        return IngressRequest(self, relation,
                              self._fetch_ingress_data(relation))

    @cache
    def is_failed(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        has an error.
        """
        if relation is None:
            return any(self.is_failed(relation) for relation in self.relations)

        if not relation.units or relation.app.name == "":
            # Juju doesn't provide JUJU_REMOTE_APP during relation-broken
            # hooks. See https://github.com/canonical/operator/issues/693
            return False

        try:
            # grab the data and validate it; might raise
            data = self._fetch_ingress_data(relation, validate=True)
        except Exception as e:
            log.exception(f"Error accessing relation databag: {e}")
            return True

        # verify that all remote units (requirer's side) publish the same
        # model/port
        prev_fields = None
        for unit in relation.units:
            if not data[unit]:
                continue
            new_fields = {field: data[unit][field]
                          for field in ("model", "port")}
            if prev_fields is None:
                prev_fields = new_fields
            if new_fields != prev_fields:
                raise RelationDataMismatchError(relation, unit)
        return False

    @cache
    def is_available(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is available.
        """
        if relation is None:
            return any(self.is_available(relation) for relation in self.relations)
        if relation.app.name == "":  # type: ignore
            # Juju doesn't provide JUJU_REMOTE_APP during relation-broken
            # hooks. See https://github.com/canonical/operator/issues/693
            return False
        return True

    @cache
    def is_ready(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is ready.

        A given relation is ready if the remote side has sent valid data.
        """
        if relation is None:
            return any(self.is_ready(relation) for relation in self.relations)
        if relation.app.name == "":  # type: ignore
            # Juju doesn't provide JUJU_REMOTE_APP during relation-broken
            # hooks. See https://github.com/canonical/operator/issues/693
            return False
        try:
            data = self._fetch_ingress_data(relation)
        except Exception:
            return False

        own_entities = (self.app, self.unit)
        return any(
            data[entity] for entity in data if entity not in own_entities
        )

    def _fetch_ingress_data(self, relation: Relation, validate=False):
        """Fetches the provider's app databag and the requirers' unit databags.
        """
        if not relation.app or not relation.app.name:
            # Handle edge case where remote app name can be missing.
            return {relation.app: {}, self.app: {}, self.unit: {}}
        unwrapped: dict = {}

        # we start by looking at the provider's app databag
        if self.unit.is_leader():
            # only leaders can read their app's data
            data = relation.data[self.app].get('data')
            deserialized = json.loads(data)
            if validate and deserialized:
                schema = INGRESS_PROVIDES_APP_SCHEMA
                jsonschema.validate(instance=deserialized, schema=schema)
            unwrapped[self.app] = deserialized

        else:
            # non-leader units cannot read/write the app databag
            unwrapped[self.app] = {}

        # then look at the requirer's (thus remote) unit databags
        related_remote_units = [obj for obj in relation.data
                                if isinstance(obj, Unit) and
                                obj is not self.unit]
        schema = INGRESS_REQUIRES_UNIT_SCHEMA
        for remote_unit in related_remote_units:
            remote_data = relation.data[remote_unit].get('data', '{}')
            deserialized = json.loads(remote_data)
            if validate and deserialized:
                jsonschema.validate(instance=deserialized, schema=schema)
            unwrapped[remote_unit] = deserialized

        return unwrapped

    # @cached_property # caching broke some tests
    @property
    def relations(self):
        """The list of Relation instances associated with this endpoint."""
        return list(self.charm.model.relations[self.endpoint])

    @property
    def proxied_endpoints(self):
        """Returns the ingress settings provided to units by this IngressPerUnitProvider.

        For example, when this IngressPerUnitProvider has provided the
        `http://foo.bar/my-model.my-app-1` and `http://foo.bar/my-model.my-app-2` URLs to
        the two units of the my-app application, the returned dictionary will be:

        ```
        {
            "my-app/1": {
                "url": "http://foo.bar/my-model.my-app-1"
            },
            "my-app/2": {
                "url": "http://foo.bar/my-model.my-app-2"
            }
        }
        ```
        """
        results = {}

        for ingress_relation in self.relations:
            data = self._fetch_ingress_data(ingress_relation)
            results.update(data[self.charm.app].get("ingress", {}))

        return results


class IngressRequest:
    """A request for per-unit ingress."""

    def __init__(self, provider: IngressPerUnitProvider, relation: Relation,
                 data):
        """Construct an IngressRequest."""
        self._provider = provider
        self._relation = relation
        self._data = data

    @property
    def model(self):
        """The name of the model the request was made from."""
        return self._get_data_from_first_unit("model")

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
        first_unit_name = self._get_data_from_first_unit("name")

        if first_unit_name:
            return first_unit_name.split("/")[0]

        return None

    @property
    def units(self):
        """The remote units."""
        return sorted(self._relation.units, key=lambda unit: unit.name)

    @property
    def port(self):
        """The backend port."""
        return self._get_data_from_first_unit("port")

    def get_host(self, unit: Unit):
        """The hostname (DNS address, ip) of the given unit."""
        return self._get_unit_data(unit, "host")

    def get_unit_name(self, unit: Unit):
        """The name of the remote unit.

        Note: This is not the same as `self.unit.name` when using CMR relations,
        since `self.unit.name` is replaced by a `remote-{UUID}` pattern.
        """
        return self._get_unit_data(unit, "name")

    def _get_data_from_first_unit(self, key: str):
        if self.units:
            first_unit_data = self._data[self.units[0]]

            if key in first_unit_data:
                return first_unit_data[key]

        return None

    def _get_unit_data(self, unit: Unit, key: str):
        if self.units:
            if unit in self.units:
                unit_data = self._data[unit]

                if key in unit_data:
                    return unit_data[key]

        return None

    def respond(self, unit: Unit, url: str):
        """Send URL back for the given unit.

        Note: only the leader can send URLs.
        """
        # Can't use `unit.name` because with CMR it's a UUID.
        remote_unit_name = self.get_unit_name(unit)
        ingress = self._data[self._provider.charm.app].setdefault("ingress", {})
        ingress.setdefault(remote_unit_name, {})["url"] = url
        self._provider.wrap(self._relation, self._data)


class RelationDataMismatchError(RelationDataError):
    """Data from different units do not match where they should."""


class IngressPerUnitConfigurationChangeEvent(RelationEvent):
    """Event representing a change in the data sent by the ingress."""


class IngressPerUnitRequirerEvents(EndpointWrapperEvents):
    """Container for IUP events."""

    ingress_changed = EventSource(IngressPerUnitConfigurationChangeEvent)


class IngressPerUnitRequirer(EndpointWrapper):
    """Implementation of the requirer of ingress_per_unit."""

    on = IngressPerUnitRequirerEvents()

    ROLE = RelationRole.requires.name
    INTERFACE = "ingress_per_unit"
    SCHEMA = INGRESS_PROVIDES_APP_SCHEMA
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
            endpoint: the name of the relation endpoint to bind to
                (defaults to "ingress-per-unit"; relation must be of interface type
                "ingress_per_unit" and have "limit: 1")
            host: Hostname to be used by the ingress provider to address the requirer
                unit; if unspecified, the pod ip of the unit will be used instead
        Request Args:
            port: the port of the service
        """
        super().__init__(charm, endpoint)
        if port:
            self.auto_data = self._complete_request(host or "", port)

        self.framework.observe(
            self.charm.on[self.endpoint].relation_changed, self._emit_ingress_change_event
        )
        self.framework.observe(
            self.charm.on[self.endpoint].relation_broken, self._emit_ingress_change_event
        )

    def _emit_ingress_change_event(self, event):
        # TODO Avoid spurious events, emit only when URL changes
        self.on.ingress_changed.emit(self.relation)

    def _complete_request(self, host: Optional[str], port: int):
        if not host:
            binding = self.charm.model.get_binding(self.endpoint)
            host = str(binding.network.bind_address)

        return {
            self.charm.unit: {
                "model": self.model.name,
                "name": self.charm.unit.name,
                "host": host,
                "port": port,
            },
        }

    def request(self, *, host: str = None, port: int):
        """Request ingress to this unit.

        Args:
            host: Hostname to be used by the ingress provider to address the requirer
                unit; if unspecified, the pod ip of the unit will be used instead
            port: the port of the service (required)
        """
        self.wrap(self.relation, self._complete_request(host, port))

    @property
    def relation(self):
        """The established Relation instance, or None."""
        return self.relations[0] if self.relations else None

    @property
    def urls(self):
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        if not self.is_ready():
            return {}
        data = self.unwrap(self.relation)
        ingress = data[self.relation.app].get("ingress", {})
        return {unit_name: unit_data["url"] for unit_name, unit_data in ingress.items()}

    @property
    def url(self):
        """The full ingress URL to reach the current unit.

        May return None if the URL isn't available yet.
        """
        if not self.urls:
            return None
        return self.urls.get(self.charm.unit.name)
