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
import logging
import typing
from functools import cached_property
from typing import Optional

import jsonschema
import yaml
from ops.charm import CharmBase, RelationEvent
from ops.framework import EventSource, Object, ObjectEvents
from ops.model import (
    ActiveStatus,
    Application,
    BlockedStatus,
    Relation,
    Unit,
    WaitingStatus,
)

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

# ======================= #
#      LIBRARY GLOBS      #
# ======================= #

SUPPORTED_VERSIONS_KEY = "_supported_versions"
INTERFACE = "ingress_per_unit"
ENDPOINT = INTERFACE.replace("_", "-")
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


# ======================= #
#  SERIALIZATION UTILS    #
# ======================= #


def _deserialize_data(data):
    # return json.loads(data) # TODO port to json
    return yaml.safe_load(data)


def _serialize_data(data):
    # return json.dumps(data) # TODO port to json
    return yaml.safe_dump(data, indent=2)


def _validate_data(data, schema):
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise DataValidationError(data, schema) from e


# ======================= #
#       EXCEPTIONS        #
# ======================= #


class IngressPerUnitException(RuntimeError):
    """Base class for errors raised by Ingress Per Unit."""


class DataValidationError(IngressPerUnitException):
    """Raised when data validation fails on IPU relation data."""


class RelationException(IngressPerUnitException):
    """Base class for relation exceptions from this library.

    Attributes:
        relation: The Relation which caused the exception.
        entity: The Application or Unit which caused the exception.
    """

    def __init__(self, relation: Relation, entity: typing.Union[Application, Unit]):
        super().__init__(relation)
        self.args = (
            f"There is an error with the relation {relation.name}:"
            f"{relation.id} from {entity.name}",
        )
        self.relation = relation
        self.entity = entity


class RelationDataMismatchError(RelationException):
    """Data from different units do not match where they should."""


class RelationPermissionError(IngressPerUnitException):
    """Raised when the ingress is requested to do something for which it lacks
    permissions.
    """

    def __init__(self, relation: Relation, entity: typing.Union[Application, Unit]):
        self.args = (
            f"Unable to write data to {relation.name}:{relation.id} for " f"{entity.name}",
        )
        self.relation = relation


# ======================= #
#         EVENTS          #
# ======================= #


class RelationAvailableEvent(RelationEvent):
    """Event triggered when a relation is ready for requests."""


class RelationFailedEvent(RelationEvent):
    """Event triggered when something went wrong with a relation."""


class RelationReadyEvent(RelationEvent):
    """Event triggered when a remote relation has the expected data."""


class RelationBrokenEvent(RelationEvent):
    """Event triggered when a remote relation has the expected data."""


class IPUEvents(ObjectEvents):
    """Container for events for IngressPerUnit."""

    available = EventSource(RelationAvailableEvent)
    ready = EventSource(RelationReadyEvent)
    failed = EventSource(RelationFailedEvent)
    broken = EventSource(RelationBrokenEvent)


class IngressPerUnitRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event.
    """


class IngressPerUnitProviderEvents(IPUEvents):
    """Container for IUP events."""

    request = EventSource(IngressPerUnitRequestEvent)


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

    @cache
    def get_status(self, relation: Relation):
        """Get the suggested status for the given Relation."""
        if self.is_failed(relation):
            return BlockedStatus(f"Error handling relation: {relation.name}")
        elif not self.is_available(relation):
            if relation.units:
                # If we have remote units but still no version, then there's
                # probably something wrong and we should be blocked.
                return BlockedStatus(f"Missing relation versions: {relation.name}")
            else:
                # Otherwise, we might just not have seen the versions yet.
                return WaitingStatus(f"Waiting on relation: {relation.name}")
        elif not self.is_ready(relation):
            return WaitingStatus(f"Waiting on relation: {relation.name}")
        return ActiveStatus()

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
            compatible = set(_deserialize_data(local_data)) & set(_deserialize_data(remote_data))
        except Exception as e:
            raise RelationDataMismatchError(relation, self.app) from e
        if compatible:
            return "v1"  # mocked

    def _publish_versions(self, relation: Relation):
        if self.unit.is_leader():
            relation.data[self.app][SUPPORTED_VERSIONS_KEY] = _serialize_data(["v1"])

    def _emit_request_event(self, event):
        self.on.request.emit(event.relation)

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
        raise NotImplementedError("implement in subclass")


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

    @cache
    def is_ready(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is ready.

        A given relation is ready if the remote side has sent valid data.
        """

        if relation is None:
            return any(self.is_ready(relation) for relation in self.relations)

        if super().is_ready(relation) is False:
            return False

        try:
            data = self._fetch_ingress_data(relation)
        except Exception as e:
            log.exception(e)
            return False

        own_entities = (self.app, self.unit)
        return any(data[entity] for entity in data if entity not in own_entities)

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
        except DataValidationError as e:
            log.warning(f"Failed to validate relation data: {e}")
            return True

        # verify that all remote units (requirer's side) publish the same
        # model/port
        prev_fields = None
        for unit in relation.units:
            if not data[unit]:
                continue
            new_fields = {field: data[unit][field] for field in ("model", "port")}
            if prev_fields is None:
                prev_fields = new_fields
            if new_fields != prev_fields:
                raise RelationDataMismatchError(relation, unit)
        return False

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        return IngressRequest(self, relation, self._fetch_ingress_data(relation))

    def _fetch_ingress_data(self, relation: Relation, validate=False):
        """Fetch and validate the provider's app databag and the
        requirers' units databags.
        """
        this_unit = self.unit
        this_app = self.app

        if not relation.app or not relation.app.name:
            # Handle edge case where remote app name can be missing.
            return {relation.app: {}, this_app: {}, this_unit: {}}

        ingress_data: dict = {}
        # we start by looking at the provider's app databag
        if this_unit.is_leader():
            # only leaders can read their app's data
            data = relation.data[this_app].get("data")
            deserialized = {}
            if validate and data:
                deserialized = _deserialize_data(data)
                _validate_data(deserialized, INGRESS_PROVIDES_APP_SCHEMA)
            ingress_data[this_app] = deserialized
        else:
            # non-leader units cannot read/write the app databag
            ingress_data[this_app] = {}

        # then look at the requirer's (thus remote) unit databags
        remote_units = [
            obj for obj in relation.data if isinstance(obj, Unit) and obj is not this_unit
        ]

        for remote_unit in remote_units:
            remote_data = relation.data[remote_unit].get("data")
            remote_deserialized = {}
            if remote_data:
                remote_deserialized = _deserialize_data(remote_data)
                if validate:
                    _validate_data(remote_deserialized, INGRESS_REQUIRES_UNIT_SCHEMA)
            ingress_data[remote_unit] = remote_deserialized

        return ingress_data

    def publish_ingress_data(
        self, relation: Relation, data: typing.Dict[typing.Union[Unit, Application], dict]
    ):
        """Publishes ingress data to the relation databag.
        :param: `data`
        """
        this_app = self.app
        this_unit = self.unit

        old_data = self._fetch_ingress_data(relation, validate=False)
        for entity in data:

            # validation step 1: check that we are not changing anything
            # except the data buckets we have access to
            if entity not in (this_app, this_unit):
                # check that we're not attempting to push new data to remote
                # units or apps
                if data[entity] != old_data.get(entity):
                    raise RelationPermissionError(relation, this_unit)
                continue

            # validation step 2: only leaders can write app data
            if entity is this_app and not this_unit.is_leader():
                raise RelationPermissionError(relation, this_unit)

            # validation step 3: if the data is meant for our application,
            # check that the data itself is valid (as per schema);
            # if it is, push it
            if entity is this_app:
                this_app_data = data[this_app]
                _validate_data(this_app_data, INGRESS_PROVIDES_APP_SCHEMA)

                # if all is well, write the data
                relation.data[this_app]["data"] = _serialize_data(this_app_data)

            # repeat for unit
            elif entity is this_unit:
                this_unit_data = data[this_unit]
                _validate_data(this_unit_data, INGRESS_PROVIDES_APP_SCHEMA)

                relation.data[this_unit]["data"] = _serialize_data(this_unit_data)

    @property
    def proxied_endpoints(self):
        """Returns the ingress settings provided to units by this
        IngressPerUnitProvider.

        For example, when this IngressPerUnitProvider has provided the
        `http://foo.bar/my-model.my-app-1` and
        `http://foo.bar/my-model.my-app-2` URLs to the two units of the
        my-app application, the returned dictionary will be:

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

    def __init__(self, provider: IngressPerUnitProvider, relation: Relation, data):
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

    @cached_property
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

    def get_unit_name(self, unit: Unit) -> Optional[str]:
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
        if not self.units:
            log.exception("This app has no units; cannot respond.")
            raise RelationException(self._relation, self.app)

        remote_unit_name = self.get_unit_name(unit)
        if remote_unit_name is None:
            raise IngressPerUnitException(f"Unable to get name of {unit!r}.")
        ingress = self._data[self._provider.charm.app].setdefault("ingress", {})
        ingress.setdefault(remote_unit_name, {})["url"] = url
        self._provider.publish_ingress_data(self._relation, self._data)


class IngressPerUnitConfigurationChangeEvent(RelationEvent):
    """Event representing a change in the data sent by the ingress."""


class IngressPerUnitRequirerEvents(IPUEvents):
    """Container for IUP events."""

    ingress_changed = EventSource(IngressPerUnitConfigurationChangeEvent)


class IngressPerUnitRequirer(IPUBase):
    """Implementation of the requirer of ingress_per_unit."""

    on = IngressPerUnitRequirerEvents()

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
                (defaults to "ingress-per-unit"; relation must be of interface
                type "ingress_per_unit" and have "limit: 1")
            host: Hostname to be used by the ingress provider to address the
            requirer unit; if unspecified, the pod ip of the unit will be used
            instead
        Request Args:
            port: the port of the service
        """
        super().__init__(charm, endpoint)

        # if instantiated with a port, and we are related, then
        # we immediately publish our ingress data  to speed up the process.
        if port:
            self._auto_data = host, port
        else:
            self._auto_data = None

        self.framework.observe(
            self.charm.on[self.endpoint].relation_changed, self._emit_ingress_change_event
        )
        self.framework.observe(
            self.charm.on[self.endpoint].relation_broken, self._emit_ingress_change_event
        )

    def _publish_auto_data(self, relation: Relation):
        if self._auto_data and self.is_available(relation):
            self._publish_ingress_data(*self._auto_data)

    def _handle_relation(self, event):
        super()._handle_relation(event)
        self._publish_auto_data(event.relation)

    def _handle_upgrade_or_leader(self, event):
        auto_data = self._auto_data
        for relation in self.relations:
            self._publish_versions(relation)
            self._publish_auto_data(relation)

    @property
    def relation(self) -> Optional[Relation]:
        """The established Relation instance, or None."""
        return self.relations[0] if self.relations else None

    def is_ready(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        is ready.

        A given relation is ready if the remote side has sent valid data.
        """
        if super().is_ready(relation) is False:
            return False

        return bool(self.url)

    @cache
    def is_failed(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified,
        has an error.
        """
        if not self.relations:  # can't fail if you can't try
            return False

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
            raw = self.relation.data[self.unit].get("data")
        except Exception as e:
            log.exception(f"Error accessing relation databag: {e}")
            return True

        if raw:
            # validate data
            data = _deserialize_data(raw)
            try:
                _validate_data(data, INGRESS_REQUIRES_UNIT_SCHEMA)
            except jsonschema.ValidationError as e:
                log.exception(f"Error validating relation data: {e}")
                return True

        return False

    def _emit_ingress_change_event(self, event):
        # TODO Avoid spurious events, emit only when URL changes
        self.on.ingress_changed.emit(self.relation)

    def _publish_ingress_data(self, host: Optional[str], port: int):
        if not host:
            binding = self.charm.model.get_binding(self.endpoint)
            host = str(binding.network.bind_address)

        data = {
            "model": self.model.name,
            "name": self.unit.name,
            "host": host,
            "port": port,
        }
        self.relation.data[self.unit]["data"] = _serialize_data(data)

    def request(self, *, host: str = None, port: int):
        """Request ingress to this unit.

        Args:
            host: Hostname to be used by the ingress provider to address the
             requirer unit; if unspecified, the pod ip of the unit will be used
             instead
            port: the port of the service (required)
        """
        self._publish_ingress_data(host, port)

    @cached_property
    def urls(self):
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        relation = self.relation
        raw = relation.data.get(relation.app, {}).get("data")

        if not raw:
            return {}

        data = _deserialize_data(raw)
        _validate_data(data, INGRESS_PROVIDES_APP_SCHEMA)

        ingress = data.get("ingress", {})
        return {unit_name: unit_data["url"] for unit_name, unit_data in ingress.items()}

    @property
    def url(self):
        """The full ingress URL to reach the current unit.

        May return None if the URL isn't available yet.
        """
        if not self.urls:
            return None
        return self.urls.get(self.charm.unit.name)
