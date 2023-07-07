# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for ingress.

This library wraps relation endpoints using the `ingress` interface
and provides a Python API for both requesting and providing per-application
ingress, with load-balancing occurring across all units.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
cd some-charm
charmcraft fetch-lib charms.traefik_k8s.v1.ingress
```

In the `metadata.yaml` of the charm, add the following:

```yaml
requires:
    ingress:
        interface: ingress
        limit: 1
```

Then, to initialise the library:

```python
from charms.traefik_k8s.v1.ingress import (IngressPerAppRequirer,
  IngressPerAppReadyEvent, IngressPerAppRevokedEvent)

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress = IngressPerAppRequirer(self, port=80)
    # The following event is triggered when the ingress URL to be used
    # by this deployment of the `SomeCharm` is ready (or changes).
    self.framework.observe(
        self.ingress.on.ready, self._on_ingress_ready
    )
    self.framework.observe(
        self.ingress.on.revoked, self._on_ingress_revoked
    )

    def _on_ingress_ready(self, event: IngressPerAppReadyEvent):
        logger.info("This app's ingress URL: %s", event.url)

    def _on_ingress_revoked(self, event: IngressPerAppRevokedEvent):
        logger.info("This app no longer has ingress")
"""

import logging
import socket
import typing
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

import yaml
from ops.charm import CharmBase, RelationBrokenEvent, RelationEvent
from ops.framework import EventSource, Object, ObjectEvents, StoredState
from ops.model import ModelError, Relation, Unit

# The unique Charmhub library identifier, never change it
LIBID = "e6de2a5cd5b34422a204668f3b8f90d2"

# Increment this major API version when introducing breaking changes
LIBAPI = 2

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

DEFAULT_RELATION_NAME = "ingress"
RELATION_INTERFACE = "ingress"

log = logging.getLogger(__name__)

try:
    import jsonschema

    DO_VALIDATION = True
except ModuleNotFoundError:
    log.warning(
        "The `ingress` library needs the `jsonschema` package to be able "
        "to do runtime data validation; without it, it will still work but validation "
        "will be disabled. \n"
        "It is recommended to add `jsonschema` to the 'requirements.txt' of your charm, "
        "which will enable this feature."
    )
    DO_VALIDATION = False

INGRESS_REQUIRES_APP_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "name": {"type": "string"},
        "strip-prefix": {"type": "string"},
        "redirect-https": {"type": "string"},
    },
    "required": ["model", "name"],
}

INGRESS_REQUIRES_UNIT_SCHEMA = {
    "type": "object",
    "properties": {
        "host": {"type": "string"},
        "port": {"type": "integer"},
    },
    "required": ["host", "port"],
}

INGRESS_PROVIDES_APP_SCHEMA = {
    "type": "object",
    "properties": {
        "ingress": {"type": "object", "properties": {"url": {"type": "string"}}},
    },
    "required": ["ingress"],
}

try:
    from typing import TypedDict
except ImportError:
    from typing_extensions import TypedDict  # py35 compat

# Model of the application data the requirer will need to provide.
RequirerAppData = TypedDict(
    "RequirerAppData",
    {
        "model": str,
        "name": str,
        "strip-prefix": bool,
        "redirect-https": bool,
    },
    total=False,
)

# Model of the data each requirer unit will need to provide.
RequirerUnitData = TypedDict("RequirerUnitData", {"host": str, "port": int})

# Provider ingress data model.
ProviderIngressData = TypedDict("ProviderIngressData", {"url": str})
# Provider application databag model.
ProviderApplicationData = TypedDict("ProviderApplicationData", {"ingress": ProviderIngressData})  # type: ignore


def _validate_data(data, schema):
    """Checks whether `data` matches `schema`.

    Will raise DataValidationError if the data is not valid, else return None.
    """
    if not DO_VALIDATION:
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise DataValidationError(data, schema) from e


class DataValidationError(RuntimeError):
    """Raised when data validation fails on IPU relation data."""


class _IngressPerAppBase(Object):
    """Base class for IngressPerUnit interface classes."""

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)

        self.charm: CharmBase = charm
        self.relation_name = relation_name
        self.app = self.charm.app
        self.unit = self.charm.unit

        observe = self.framework.observe
        rel_events = charm.on[relation_name]
        observe(rel_events.relation_created, self._handle_relation)
        observe(rel_events.relation_joined, self._handle_relation)
        observe(rel_events.relation_changed, self._handle_relation)
        observe(rel_events.relation_broken, self._handle_relation_broken)
        observe(charm.on.leader_elected, self._handle_upgrade_or_leader)  # type: ignore
        observe(charm.on.upgrade_charm, self._handle_upgrade_or_leader)  # type: ignore

    @property
    def relations(self):
        """The list of Relation instances associated with this endpoint."""
        return list(self.charm.model.relations[self.relation_name])

    def _handle_relation(self, event):
        """Subclasses should implement this method to handle a relation update."""
        pass

    def _handle_relation_broken(self, event):
        """Subclasses should implement this method to handle a relation breaking."""
        pass

    def _handle_upgrade_or_leader(self, event):
        """Subclasses should implement this method to handle upgrades or leadership change."""
        pass


class _IPAEvent(RelationEvent):
    __args__: Tuple[str, ...] = ()
    __optional_kwargs__: Dict[str, Any] = {}

    @classmethod
    def __attrs__(cls):
        return cls.__args__ + tuple(cls.__optional_kwargs__.keys())

    def __init__(self, handle, relation, *args, **kwargs):
        super().__init__(handle, relation)

        if not len(self.__args__) == len(args):
            raise TypeError("expected {} args, got {}".format(len(self.__args__), len(args)))

        for attr, obj in zip(self.__args__, args):
            setattr(self, attr, obj)
        for attr, default in self.__optional_kwargs__.items():
            obj = kwargs.get(attr, default)
            setattr(self, attr, obj)

    def snapshot(self):
        dct = super().snapshot()
        for attr in self.__attrs__():
            obj = getattr(self, attr)
            try:
                dct[attr] = obj
            except ValueError as e:
                raise ValueError(
                    "cannot automagically serialize {}: "
                    "override this method and do it "
                    "manually.".format(obj)
                ) from e

        return dct

    def restore(self, snapshot) -> None:
        super().restore(snapshot)
        for attr, obj in snapshot.items():
            setattr(self, attr, obj)


class IngressPerAppDataProvidedEvent(_IPAEvent):
    """Event representing that ingress data has been provided for an app."""

    __args__ = ("name", "model", "hosts", "strip_prefix", "redirect_https")

    if typing.TYPE_CHECKING:
        name: Optional[str] = None
        model: Optional[str] = None
        # sequence of hostname, port dicts
        hosts: Sequence[RequirerUnitData] = ()
        strip_prefix: bool = False
        redirect_https: bool = False


class IngressPerAppDataRemovedEvent(RelationEvent):
    """Event representing that ingress data has been removed for an app."""


class IngressPerAppProviderEvents(ObjectEvents):
    """Container for IPA Provider events."""

    data_provided = EventSource(IngressPerAppDataProvidedEvent)
    data_removed = EventSource(IngressPerAppDataRemovedEvent)


class NotReadyError(RuntimeError):
    """Raised when a relation is not ready."""


@dataclass
class IngressRequirerData:
    """Data exposed by the ingress requirer to the provider."""

    app: RequirerAppData
    units: List[RequirerUnitData]


class IngressPerAppProvider(_IngressPerAppBase):
    """Implementation of the provider of ingress."""

    on = IngressPerAppProviderEvents()  # type: ignore

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        """Constructor for IngressPerAppProvider.

        Args:
            charm: The charm that is instantiating the instance.
            relation_name: The name of the relation endpoint to bind to
                (defaults to "ingress").
        """
        super().__init__(charm, relation_name)

    def _handle_relation(self, event):
        # created, joined or changed: if remote side has sent the required data:
        # notify listeners.
        if self.is_ready(event.relation):
            data = self.get_data(event.relation)
            self.on.data_provided.emit(  # type: ignore
                event.relation,
                data.app["name"],
                data.app["model"],
                data.units,
                data.app.get("strip-prefix", False),
                data.app.get("redirect-https", False),
            )

    def _handle_relation_broken(self, event):
        self.on.data_removed.emit(event.relation)  # type: ignore

    def wipe_ingress_data(self, relation: Relation):
        """Clear ingress data from relation."""
        assert self.unit.is_leader(), "only leaders can do this"
        try:
            relation.data
        except ModelError as e:
            log.warning(
                "error {} accessing relation data for {!r}. "
                "Probably a ghost of a dead relation is still "
                "lingering around.".format(e, relation.name)
            )
            return
        del relation.data[self.app]["ingress"]

    def _get_requirer_units_data(self, relation: Relation) -> List[RequirerUnitData]:
        """Fetch and validate the requirer's app databag.

        We cast port to int for convenience.
        """
        out: List[RequirerUnitData] = []

        unit: Unit
        for unit in relation.units:
            databag = relation.data[unit]
            remote_unit_data: Dict[str, Optional[Union[int, str]]] = {}
            for key in ("host", "port"):
                remote_unit_data[key] = databag.get(key)
            remote_unit_data["port"] = (
                int(remote_unit_data["port"]) if remote_unit_data["port"] else None
            )
            _validate_data(remote_unit_data, INGRESS_REQUIRES_UNIT_SCHEMA)
            out.append(typing.cast(RequirerUnitData, remote_unit_data))
        return out

    def _get_requirer_app_data(self, relation: Relation) -> RequirerAppData:
        """Fetch and validate the requirer's app databag."""
        app = relation.app
        if app is None:
            raise NotReadyError(relation)

        databag = relation.data[app]
        remote_app_data: Dict[str, Union[int, str]] = {}

        for k in ("model", "name", "mode", "strip-prefix", "redirect-https"):
            v = databag.get(k)
            if v is not None:
                remote_app_data[k] = v

        _validate_data(remote_app_data, INGRESS_REQUIRES_APP_SCHEMA)

        remote_app_data["strip-prefix"] = bool(
            remote_app_data.get("strip-prefix", "false") == "true"
        )
        remote_app_data["redirect-https"] = bool(
            remote_app_data.get("redirect-https", "false") == "true"
        )
        return typing.cast(RequirerAppData, remote_app_data)

    def get_data(self, relation: Relation) -> IngressRequirerData:
        """Fetch the remote (requirer) app and units' databags."""
        return IngressRequirerData(
            self._get_requirer_app_data(relation), self._get_requirer_units_data(relation)
        )

    def is_ready(self, relation: Optional[Relation] = None):
        """The Provider is ready if the requirer has sent valid data."""
        if not relation:
            return any(map(self.is_ready, self.relations))

        try:
            self.get_data(relation)
        except DataValidationError as e:
            log.error("Provider not ready; validation error encountered: %s" % str(e))
            return False
        return True

    def _provided_url(self, relation: Relation) -> ProviderIngressData:  # type: ignore
        """Fetch and validate this app databag; return the ingress url."""
        if not relation.app or not relation.app.name or not self.unit.is_leader():  # type: ignore
            # Handle edge case where remote app name can be missing, e.g.,
            # relation_broken events.
            # Also, only leader units can read own app databags.
            # FIXME https://github.com/canonical/traefik-k8s-operator/issues/34
            return typing.cast(ProviderIngressData, {})  # noqa

        # fetch the provider's app databag
        raw_data = relation.data[self.app].get("ingress")
        if not raw_data:
            raise RuntimeError("This application did not `publish_url` yet.")

        ingress: ProviderIngressData = yaml.safe_load(raw_data)
        _validate_data({"ingress": ingress}, INGRESS_PROVIDES_APP_SCHEMA)
        return ingress

    def publish_url(self, relation: Relation, url: str):
        """Publish to the app databag the ingress url."""
        ingress = {"url": url}
        ingress_data = {"ingress": ingress}
        _validate_data(ingress_data, INGRESS_PROVIDES_APP_SCHEMA)
        relation.data[self.app]["ingress"] = yaml.safe_dump(ingress)

    @property
    def proxied_endpoints(self):
        """Returns the ingress settings provided to applications by this IngressPerAppProvider.

        For example, when this IngressPerAppProvider has provided the
        `http://foo.bar/my-model.my-app` URL to the my-app application, the returned dictionary
        will be:

        ```
        {
            "my-app": {
                "url": "http://foo.bar/my-model.my-app"
            }
        }
        ```
        """
        results = {}

        for ingress_relation in self.relations:
            assert (
                ingress_relation.app
            ), "no app in relation (shouldn't happen)"  # for type checker
            results[ingress_relation.app.name] = self._provided_url(ingress_relation)

        return results


class IngressPerAppReadyEvent(_IPAEvent):
    """Event representing that ingress for an app is ready."""

    __args__ = ("url",)
    if typing.TYPE_CHECKING:
        url: Optional[str] = None


class IngressPerAppRevokedEvent(RelationEvent):
    """Event representing that ingress for an app has been revoked."""


class IngressPerAppRequirerEvents(ObjectEvents):
    """Container for IPA Requirer events."""

    ready = EventSource(IngressPerAppReadyEvent)
    revoked = EventSource(IngressPerAppRevokedEvent)


class IngressPerAppRequirer(_IngressPerAppBase):
    """Implementation of the requirer of the ingress relation."""

    on = IngressPerAppRequirerEvents()  # type: ignore

    # used to prevent spurious urls to be sent out if the event we're currently
    # handling is a relation-broken one.
    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        strip_prefix: bool = False,
        redirect_https: bool = False,
    ):
        """Constructor for IngressRequirer.

        The request args can be used to specify the ingress properties when the
        instance is created. If any are set, at least `port` is required, and
        they will be sent to the ingress provider as soon as it is available.
        All request args must be given as keyword args.

        Args:
            charm: the charm that is instantiating the library.
            relation_name: the name of the relation endpoint to bind to (defaults to `ingress`);
                relation must be of interface type `ingress` and have "limit: 1")
            host: Hostname to be used by the ingress provider to address the requiring
                application; if unspecified, the default Kubernetes service name will be used.
            strip_prefix: configure Traefik to strip the path prefix.
            redirect_https: redirect incoming requests to the HTTPS.

        Request Args:
            port: the port of the service
        """
        super().__init__(charm, relation_name)
        self.charm: CharmBase = charm
        self.relation_name = relation_name
        self._strip_prefix = strip_prefix
        self._redirect_https = redirect_https

        self._stored.set_default(current_url=None)  # type: ignore

        # if instantiated with a port, and we are related, then
        # we immediately publish our ingress data  to speed up the process.
        if port:
            self._auto_data = host, port
        else:
            self._auto_data = None

    def _handle_relation(self, event):
        # created, joined or changed: if we have auto data: publish it
        self._publish_auto_data(event.relation)

        if self.is_ready():
            # Avoid spurious events, emit only when there is a NEW URL available
            new_url = (
                None
                if isinstance(event, RelationBrokenEvent)
                else self._get_url_from_relation_data()
            )
            if self._stored.current_url != new_url:  # type: ignore
                self._stored.current_url = new_url  # type: ignore
                self.on.ready.emit(event.relation, new_url)  # type: ignore

    def _handle_relation_broken(self, event):
        self._stored.current_url = None  # type: ignore
        self.on.revoked.emit(event.relation)  # type: ignore

    def _handle_upgrade_or_leader(self, event):
        """On upgrade/leadership change: ensure we publish the data we have."""
        for relation in self.relations:
            self._publish_auto_data(relation)

    def is_ready(self):
        """The Requirer is ready if the Provider has sent valid data."""
        try:
            return bool(self._get_url_from_relation_data())
        except DataValidationError as e:
            log.error("Requirer not ready; validation error encountered: %s" % str(e))
            return False

    def _publish_auto_data(self, relation: Relation):
        if self._auto_data and self.unit.is_leader():
            host, port = self._auto_data
            self.provide_ingress_requirements(host=host, port=port)

    def provide_ingress_requirements(self, *, host: Optional[str] = None, port: int):
        """Publishes the data that Traefik needs to provide ingress.

        Args:
            host: Hostname to be used by the ingress provider to address the
             requirer unit; if unspecified, FQDN will be used instead
            port: the port of the service (required)
        """
        # get only the leader to publish the data since we only
        # require one unit to publish it -- it will not differ between units,
        # unlike in ingress-per-unit.
        assert self.relation, "no relation"

        if self.unit.is_leader():
            app_data = {
                "model": self.model.name,
                "name": self.app.name,
            }

            if self._strip_prefix:
                app_data["strip-prefix"] = "true"

            if self._redirect_https:
                app_data["redirect-https"] = "true"

            _validate_data(app_data, INGRESS_REQUIRES_APP_SCHEMA)
            self.relation.data[self.app].update(app_data)

        if not host:
            host = socket.getfqdn()

        unit_data = {
            "host": host,
            "port": port,
        }
        _validate_data(unit_data, INGRESS_REQUIRES_UNIT_SCHEMA)

        unit_data["port"] = str(port)
        self.relation.data[self.app].update(unit_data)

    @property
    def relation(self):
        """The established Relation instance, or None."""
        return self.relations[0] if self.relations else None

    def _get_url_from_relation_data(self) -> Optional[str]:
        """The full ingress URL to reach the current unit.

        Returns None if the URL isn't available yet.
        """
        relation = self.relation
        if not relation or not relation.app:
            return None

        # fetch the provider's app databag
        try:
            raw = relation.data.get(relation.app, {}).get("ingress")
        except ModelError as e:
            log.debug(
                f"Error {e} attempting to read remote app data; "
                f"probably we are in a relation_departed hook"
            )
            return None

        if not raw:
            return None

        ingress: ProviderIngressData = yaml.safe_load(raw)
        _validate_data({"ingress": ingress}, INGRESS_PROVIDES_APP_SCHEMA)
        return ingress["url"]

    @property
    def url(self) -> Optional[str]:
        """The full ingress URL to reach the current unit.

        Returns None if the URL isn't available yet.
        """
        data = self._stored.current_url or self._get_url_from_relation_data()  # type: ignore
        assert isinstance(data, (str, type(None)))  # for static checker
        return data
