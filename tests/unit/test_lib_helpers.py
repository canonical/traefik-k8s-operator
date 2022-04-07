# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""
import typing
from contextlib import contextmanager
from functools import partial
from unittest.mock import patch

from charms.traefik_k8s.v0.ingress import (
    IngressPerAppProvider,
    IngressPerAppRequest,
    IngressPerAppRequirer,
)
from charms.traefik_k8s.v0.ingress_per_unit import (
    DEFAULT_RELATION_NAME,
    RELATION_INTERFACE,
    IngressPerUnitProvider,
    IngressPerUnitRequirer,
    ProviderApplicationData,
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
        self.app_name = f"{DEFAULT_RELATION_NAME}-remote"
        self.unit_name = f"{self.app_name}/0"

        class MRRMTestEvents(CharmEvents):
            __name__ = self.app_name

        class MRRMTestCharm(CharmBase):
            __name__ = self.app_name
            on = MRRMTestEvents()
            meta = CharmMeta(
                {
                    self.ROLE: {
                        DEFAULT_RELATION_NAME: {
                            "role": self.ROLE,
                            "interface": RELATION_INTERFACE,
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

    @property
    def relation(self):
        """The Relation instance, if created."""
        return self.harness.model.get_relation(self.relation_name, self.relation_id)

    def relate(self, relation_name: str = None):
        """Create a relation to the charm under test.

        Starts the version negotiation, and returns the Relation instance.
        """
        if not relation_name:
            relation_name = self.relation_name
        self.relation_id = self.harness.add_relation(relation_name, self.app_name)
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

    def publish_url(self, relation: Relation, unit_name: str, url: str):
        with self.remote_context(self.relation):
            super().publish_url(relation, unit_name, url)
        self.harness._charm.on.ingress_per_unit_relation_changed.emit(self.relation)

    def publish_ingress_data(self, relation: Relation, data: ProviderApplicationData):
        with self.remote_context(self.relation):
            super().publish_url(relation, data)
        self.harness._charm.on.ingress_per_unit_relation_changed.emit(self.relation)


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

    def publish_ingress_data(self, *, host: str = None, port: int):
        with self.remote_context(self.relation):
            super().publish_ingress_data(host=host, port=port)
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
