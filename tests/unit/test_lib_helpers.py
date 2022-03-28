# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""
import typing
from contextlib import contextmanager
from functools import cached_property, partial
from inspect import getmembers
from unittest.mock import patch

from charms.traefik_k8s.v0.ingress import (
    IngressPerAppProvider,
    IngressPerAppRequest,
    IngressPerAppRequirer,
)
from charms.traefik_k8s.v0.ingress_per_unit import (
    ENDPOINT,
    INTERFACE,
    IngressPerUnitProvider,
    IngressPerUnitRequirer,
    IngressRequest,
    IPUBase,
)
from ops.charm import CharmBase, CharmEvents, CharmMeta
from ops.model import Relation
from serialized_data_interface import MockRemoteRelationMixin as MockRemoteIPAMixin


class MockRemoteIPUMixin:
    """Adds unit testing helpers to EndpointWrapper."""

    ROLE: str
    LIMIT: typing.Optional[int]

    def __init__(self, harness):
        """Initialize the mock provider / requirer."""
        self.app_name = f"{ENDPOINT}-remote"
        self.unit_name = f"{self.app_name}/0"

        class MRRMTestEvents(CharmEvents):
            __name__ = self.app_name

        class MRRMTestCharm(CharmBase):
            __name__ = self.app_name
            on = MRRMTestEvents()
            meta = CharmMeta(
                {
                    self.ROLE: {
                        ENDPOINT: {
                            "role": self.ROLE,
                            "interface": INTERFACE,
                            "limit": self.LIMIT,
                        },
                    },
                }
            )
            app = harness.model.get_app(self.app_name)
            unit = harness.model.get_unit(self.unit_name)

        if harness.model.name is None:
            harness._backend.model_name = "test-model"

        super().__init__(MRRMTestCharm(harness.framework))
        self.harness = harness
        self.relation_id = None
        self.num_units = 0
        self._remove_caching()

    def _remove_caching(self):
        # We use the caching helpers from functools to save recalculations, but during
        # tests they can interfere with seeing the updated state, so we strip them off.
        is_ew = lambda v: isinstance(v, IPUBase)  # noqa: E731
        is_cp = lambda v: isinstance(v, cached_property)  # noqa: E731
        is_cf = lambda v: hasattr(v, "cache_clear")  # noqa: E731
        classes = [
            IPUBase,
            IngressPerUnitRequirer,
            IngressPerUnitProvider,
            type(self),
            *[type(instance) for _, instance in getmembers(self.harness.charm, is_ew)],
        ]
        for cls in classes:
            for attr, prop in getmembers(cls, lambda v: is_cp(v) or is_cf(v)):
                if is_cp(prop):
                    setattr(cls, attr, property(prop.func))
                else:
                    setattr(cls, attr, prop.__wrapped__)

    @property
    def relation(self):
        """The Relation instance, if created."""
        return self.harness.model.get_relation(self.endpoint, self.relation_id)

    def relate(self, endpoint: str = None):
        """Create a relation to the charm under test.

        Starts the version negotiation, and returns the Relation instance.
        """
        if not endpoint:
            endpoint = self.endpoint
        self.relation_id = self.harness.add_relation(endpoint, self.app_name)
        self.add_unit()
        return self.relation

    @contextmanager
    def remote_context(self, relation: Relation):
        """Temporarily change the context to the remote side of the relation.

        The test runs within the context of the local charm under test.  This
        means that the relation data on the remote side cannot be written, the
        app and units references are from the local charm's perspective, etc.
        This temporarily patches things to behave as if we were running on the
        remote charm instead.
        """
        with patch.multiple(
            self.harness._backend,
            app_name=self.app.name,
            unit_name=getattr(self.unit, "name", None),
            is_leader=lambda: True,
        ):
            with patch.multiple(
                relation, app=self.harness.charm.app, units={self.harness.charm.unit}
            ):
                with patch.object(self.unit, "_is_our_unit", True):
                    yield

    def add_unit(self):
        """Add a unit to the relation."""
        unit_name = f"{self.app_name}/{self.num_units}"
        self.harness.add_relation_unit(self.relation_id, unit_name)
        self.num_units += 1

    def is_available(self, relation: Relation = None):
        """Same as EndpointWrapper.is_available, but with the remote context."""
        if relation is None:
            return any(self.is_available(relation) for relation in self.relations)
        with self.remote_context(relation):
            return super().is_available(relation)

    def is_ready(self, relation: Relation = None):
        """Same as EndpointWrapper.is_ready, but with the remote context."""
        if relation is None:
            return any(self.is_ready(relation) for relation in self.relations)
        with self.remote_context(relation):
            return super().is_ready(relation)

    def is_failed(self, relation: Relation = None):
        """Same as EndpointWrapper.is_failed, but with the remote context."""
        if not self.relations:
            return False
        if relation is None:
            return any(self.is_failed(relation) for relation in self.relations)
        with self.remote_context(relation):
            return super().is_failed(relation)


class MockIPUProvider(MockRemoteIPUMixin, IngressPerUnitProvider):
    """Class to help with unit testing ingress requirer charms.

    Exactly the same as the normal IngressPerUnitProvider but, acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    ROLE = "provides"
    LIMIT = None

    def _mock_respond(self, unit, url, _respond, _relation):
        with self.remote_context(_relation):
            _respond(unit, url)

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        # reflect the relation for the request so that it appears remote
        with self.remote_context(relation):
            request = MockIngressPerUnitRequest(self, relation, self._fetch_ingress_data(relation))
            request.respond = partial(
                self._mock_respond, _respond=request.respond, _relation=relation
            )
            return request


class MockIngressPerUnitRequest(IngressRequest):
    """Testing wrapper for an IngressRequest.

    Exactly the same as the normal IngressRequest but acts as if it's on the
    remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    @property
    def app(self):
        """The remote application."""
        return self._provider.harness.charm.app

    @property
    def units(self):
        """The remote units."""
        return [self._provider.harness.charm.unit]


class MockIPURequirer(MockRemoteIPUMixin, IngressPerUnitRequirer):
    """Class to help with unit testing ingress provider charms.

    Exactly the same as the normal IngressPerUnitRequirer, but acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    requests are sent.
    """

    ROLE = "requires"
    LIMIT = 1

    @property
    def urls(self):
        with self.remote_context(self.relation):
            return super().urls

    def request(self, *, host: str = None, port: int):
        with self.remote_context(self.relation):
            super().request(host=host, port=port)
        self.harness._charm.on.ingress_per_unit_relation_changed.emit(self.relation)


class MockIPAProvider(MockRemoteIPAMixin, IngressPerAppProvider):
    """Class to help with unit testing ingress requirer charms.

    Exactly the same as the normal IngressPerAppProvider but, acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        # reflect the relation for the request so that it appears remote
        return MockIngressPerAppRequest(self, relation)


class MockIngressPerAppRequest(IngressPerAppRequest):
    """Testing wrapper for an IngressPerAppRequest.

    Exactly the same as the normal IngressPerAppRequest but acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    @property
    def app(self):
        """The remote application."""
        return self._provider.harness.charm.app


class MockIPARequirer(MockRemoteIPAMixin, IngressPerAppRequirer):
    """Class to help with unit testing ingress provider charms.

    Exactly the same as the normal IngressPerAppRequirer, but acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    requests are sent.
    """

    @property
    def url(self):
        """The full ingress URL to reach the application.

        May return None is the URL is not available yet.
        """
        with self.remote_context(self.relation):
            return super().url
