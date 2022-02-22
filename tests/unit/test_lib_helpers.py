# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""

from charms.traefik_k8s.v0.ingress import (
    IngressPerAppProvider,
    IngressPerAppRequest,
    IngressPerAppRequirer,
)
from charms.traefik_k8s.v0.ingress_per_unit import (
    IngressPerUnitProvider,
    IngressPerUnitRequirer,
    IngressRequest,
)
from ops.model import Relation
from serialized_data_interface.testing import MockRemoteRelationMixin


class MockIPUProvider(MockRemoteRelationMixin, IngressPerUnitProvider):
    """Class to help with unit testing ingress requirer charms.

    Exactly the same as the normal IngressPerUnitProvider but, acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        # reflect the relation for the request so that it appears remote
        return MockIngressPerUnitRequest(self, relation)


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


class MockIPURequirer(MockRemoteRelationMixin, IngressPerUnitRequirer):
    """Class to help with unit testing ingress provider charms.

    Exactly the same as the normal IngressPerUnitRequirer, but acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    requests are sent.
    """

    @property
    def urls(self):
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        with self.remote_context(self.relation):
            return super().urls


class MockIPAProvider(MockRemoteRelationMixin, IngressPerAppProvider):
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


class MockIPARequirer(MockRemoteRelationMixin, IngressPerAppRequirer):
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
