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
import typing
from functools import cached_property
from typing import Optional

import jsonschema
import yaml
from ops.charm import CharmBase, RelationEvent, RelationRole
from ops.framework import EventSource, Object, ObjectEvents
from ops.model import Relation, Unit, Application

try:
    from serialized_data_interface import EndpointWrapper
    from serialized_data_interface.errors import RelationDataError
except ImportError:
    import os

    library_name = os.path.basename(__file__)
    raise ModuleNotFoundError(
        "To use the '{}' library, you must include "
        "the '{}' package in your dependencies".format(library_name,
                                                       "serialized_data_interface")
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
log.setLevel('INFO')  # TODO do not merge, for testing only

SUPPORTED_VERSIONS_KEY = '_supported_versions'

INTERFACE = 'ingress_per_unit'
ENDPOINT = INTERFACE.replace('_', '-')

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


class RelationAvailableEvent(RelationEvent):
    """Event triggered when a relation is ready for requests."""


class RelationFailedEvent(RelationEvent):
    """Event triggered when something went wrong with a relation."""


class RelationReadyEvent(RelationEvent):
    """Event triggered when a remote relation has the expected data."""


class RelationBrokenEvent(RelationEvent):
    """Event triggered when a remote relation has the expected data."""


class IPUEvents(ObjectEvents):
    """Container for events for EndpointWrapper."""

    available = EventSource(RelationAvailableEvent)
    ready = EventSource(RelationReadyEvent)
    failed = EventSource(RelationFailedEvent)
    broken = EventSource(RelationBrokenEvent)


class IngressPerUnitError(RuntimeError):
    """Base class for errors raised by Ingress Per Unit."""


class RelationPermissionError(IngressPerUnitError):
    """Raised when the ingress is requested to do something for which it lacks
    permissions.
    """

    def __init__(self, relation: Relation,
                 entity: typing.Union[Application, Unit]):
        self.args = (
            f"Unable to write data to {relation.name}:{relation.id} for "
            f"{entity.name}",
        )
        self.relation = relation


class IngressPerUnitRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more semantically meaningful.
    """


class IngressPerUnitProviderEvents(IPUEvents):
    """Container for IUP events."""

    request = EventSource(IngressPerUnitRequestEvent)


def deserialize_data(data):
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        # TODO remove after both sides are ported to json
        import yaml
        return yaml.safe_load(data)


def serialize_data(data):
    # return json.dumps(data) # TODO port to json
    return yaml.safe_dump(data)


class IPUBase(Object):
    """Base class for IPU."""
    _IPUEvtType = typing.TypeVar("_IPUEvtType", bound=IPUEvents)
    on: _IPUEvtType

    def __init__(self, charm: CharmBase, endpoint: str = ENDPOINT):
        """Constructor for IngressPerUnitProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "ingress-per-unit").
        """
        super().__init__(charm, endpoint)
        self.charm = charm
        self.endpoint = endpoint

        observe = self.framework.observe
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

    # @cached_property
    @property
    def relations(self):
        """The list of Relation instances associated with this endpoint."""
        return list(self.charm.model.relations[self.endpoint])

    def _handle_relation(self, event):
        self._publish_versions(event.relation)
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
            self._publish_versions(relation)

    def get_version(self, relation: Relation):
        data = relation.data
        local_data = data[self.app].get(SUPPORTED_VERSIONS_KEY)
        remote_data = data[relation.app].get(SUPPORTED_VERSIONS_KEY)
        if not (local_data and remote_data):
            return None

        try:
            compatible = (set(deserialize_data(local_data)) &
                          set(deserialize_data(remote_data)))
        except Exception as e:
            raise RelationDataMismatchError(relation, self.app) from e
        if compatible:
            return 'v1'  # mocked

    def _publish_versions(self, relation: Relation):
        if self.unit.is_leader():
            relation.data[self.app][SUPPORTED_VERSIONS_KEY] = \
                serialize_data(['v1'])

    def _emit_request_event(self, event):
        self.on.request.emit(event.relation)

    @cache
    def is_available(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is available.
        """
        if relation is None:
            return any(
                self.is_available(relation) for relation in self.relations)
        if relation.app.name == "":  # type: ignore
            # Juju doesn't provide JUJU_REMOTE_APP during relation-broken
            # hooks. See https://github.com/canonical/operator/issues/693
            return False
        return bool(self.get_version(relation))

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

    def is_failed(self, relation: Relation = None):
        raise NotImplementedError('implement in subclass')


class IngressPerUnitProvider(IPUBase):
    """Implementation of the provider of ingress_per_unit."""

    on = IngressPerUnitProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = ENDPOINT):
        """Constructor for IngressPerUnitProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "ingress-per-unit").
        """
        super().__init__(charm, endpoint)
        observe = self.framework.observe
        observe(self.on.ready, self._emit_request_event)

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        return IngressRequest(self, relation,
                              self._fetch_ingress_data(relation))

    @cache
    def is_ready(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is ready.

        A given relation is ready if the remote side has sent valid data.
        """
        if super().is_ready is False:
            return False

        try:
            data = self._fetch_ingress_data(relation)
        except Exception as e:
            log.exception(e)
            return False

        own_entities = (self.app, self.unit)
        return any(
            data[entity] for entity in data if entity not in own_entities
        )

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
            deserialized = {}
            if validate and data:
                deserialized = deserialize_data(data)
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
            remote_data = relation.data[remote_unit].get('data')
            deserialized = {}
            if remote_data:
                deserialized = deserialize_data(remote_data)
                if validate:
                    jsonschema.validate(instance=deserialized, schema=schema)
            unwrapped[remote_unit] = deserialized

        return unwrapped

    def push_ingress_data(self, relation: Relation, data: dict):
        app = self.app
        unit = self.unit

        old_data = self._fetch_ingress_data(relation, validate=False)
        for entity in data:

            # validation step 1: check that we are not changing anything
            # except the data buckets we have access to
            if entity not in (app, unit):
                # check that we're not attempting to push new data to remote
                # units or apps
                if data[entity] != old_data.get(entity):
                    raise RelationPermissionError(relation, entity)
                continue

            # only leaders can write app data
            if entity is app and not unit.is_leader():
                raise RelationPermissionError(relation, app)

            # validation step 2: check that the data itself is valid (as per schema)
            if entity is app:
                schema = INGRESS_PROVIDES_APP_SCHEMA
                app_data = data[app]
                jsonschema.validate(instance=app_data, schema=schema)

                # if all is well, write the data
                relation.data[app]["data"] = serialize_data(app_data)

            # repeat for  unit
            if entity is unit:
                schema = INGRESS_PROVIDES_APP_SCHEMA
                unit_data = data[unit]
                jsonschema.validate(instance=unit_data, schema=schema)

                relation.data[unit]["data"] = serialize_data(unit_data)

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
        self._provider.push_ingress_data(self._relation, self._data)


class RelationDataMismatchError(RelationDataError):
    """Data from different units do not match where they should."""


class IngressPerUnitConfigurationChangeEvent(RelationEvent):
    """Event representing a change in the data sent by the ingress."""


class IngressPerUnitRequirerEvents(IPUEvents):
    """Container for IUP events."""

    ingress_changed = EventSource(IngressPerUnitConfigurationChangeEvent)


class IngressPerUnitRequirer(IPUBase):
    """Implementation of the requirer of ingress_per_unit."""

    on = IngressPerUnitRequirerEvents()

    ROLE = RelationRole.requires.name
    INTERFACE = "ingress_per_unit"
    SCHEMA = INGRESS_PROVIDES_APP_SCHEMA
    LIMIT = 1

    def __init__(
            self,
            charm: CharmBase,
            endpoint: str = ENDPOINT,
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
            self._send_request(host, port)

        self.framework.observe(
            self.charm.on[self.endpoint].relation_changed,
            self._emit_ingress_change_event
        )
        self.framework.observe(
            self.charm.on[self.endpoint].relation_broken,
            self._emit_ingress_change_event
        )

    @property
    def relation(self) -> Optional[Relation]:
        """The established Relation instance, or None."""
        return self.relations[0] if self.relations else None

    def _emit_ingress_change_event(self, event):
        # TODO Avoid spurious events, emit only when URL changes
        self.on.ingress_changed.emit(self.relation)

    def _send_request(self, host: Optional[str], port: int):
        if not host:
            binding = self.charm.model.get_binding(self.endpoint)
            host = str(binding.network.bind_address)

        data = {
            "model": self.model.name,
            "name": self.unit.name,
            "host": host,
            "port": port,
        }
        self.relation.data[self.unit]['data'] = serialize_data(data)

    def request(self, *, host: str = None, port: int):
        """Request ingress to this unit.

        Args:
            host: Hostname to be used by the ingress provider to address the requirer
                unit; if unspecified, the pod ip of the unit will be used instead
            port: the port of the service (required)
        """
        self._send_request(host, port)

    @cached_property
    def urls(self):
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        relation = self.relation
        raw = relation.data.get(relation.app, {}).get('data')

        if not raw:
            return {}

        data = deserialize_data(raw)

        ingress = data.get("ingress", {})
        return {unit_name: unit_data["url"] for unit_name, unit_data in
                ingress.items()}

    @property
    def url(self):
        """The full ingress URL to reach the current unit.

        May return None if the URL isn't available yet.
        """
        if not self.urls:
            return None
        return self.urls.get(self.charm.unit.name)

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

        if not self.get_version(relation):
            return True

        try:
            # grab the data and validate it; might raise
            raw = self.relation.data[self.unit].get('data')
        except Exception as e:
            log.exception(f"Error accessing relation databag: {e}")
            return True

        if raw:
            # validate data
            data = deserialize_data(raw)
            try:
                jsonschema.validate(instance=data,
                                    schema=INGRESS_REQUIRES_UNIT_SCHEMA)
            except jsonschema.ValidationError as e:
                log.exception(f"Error validating relation data: {e}")
                return True

        return False

    def is_ready(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is ready.

        A given relation is ready if the remote side has sent valid data.
        """
        if super().is_ready(relation) is False:
            return False

        return bool(self.url)
