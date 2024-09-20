# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.
from contextlib import ExitStack
from unittest.mock import PropertyMock, patch

import pytest
from ops.model import ActiveStatus
from scenario import Container, Context, State
from scenario.context import CharmEvents

from charm import TraefikIngressCharm

on = CharmEvents()


@pytest.fixture(autouse=True)
def patch_all():
    with ExitStack() as stack:
        stack.enter_context(patch("charm.KubernetesServicePatch"))
        stack.enter_context(patch("lightkube.core.client.GenericSyncClient"))
        stack.enter_context(
            patch(
                "charm.TraefikIngressCharm._static_config_changed",
                PropertyMock(return_value=False),
            )
        )
        stack.enter_context(
            patch("charm.TraefikIngressCharm._external_host", PropertyMock(return_value="foo.bar"))
        )
        stack.enter_context(patch("traefik.Traefik.is_ready", PropertyMock(return_value=True)))
        stack.enter_context(
            patch("charm.TraefikIngressCharm.version", PropertyMock(return_value="1.2.3"))
        )
        yield


@pytest.fixture
def state():
    containers = [Container(name="traefik", can_connect=True)]
    return State(
        config={"routing_mode": "path"},
        containers=containers,
    )


@pytest.fixture
def context():
    return Context(charm_type=TraefikIngressCharm)


def test_workload_version_is_set_on_update_status(context, state):
    # GIVEN an initial state without the workload version set
    out = context.run(on.start(), state)
    assert out.unit_status == ActiveStatus("Serving at foo.bar")
    assert out.workload_version == ""

    # WHEN update-status is triggered
    out = context.run(on.update_status(), out)

    # THEN the workload version is set
    assert out.workload_version == "1.2.3"


def test_workload_version_clears_on_stop(context, state):
    # GIVEN a state after update-status (which we know sets the workload version)
    # GIVEN an initial state with the workload version set
    out = context.run(on.update_status(), state)
    assert out.unit_status == ActiveStatus("Serving at foo.bar")
    assert out.workload_version == "1.2.3"

    # WHEN the charm is stopped
    out = context.run(on.stop(), out)

    # THEN workload version is cleared
    assert out.workload_version == ""
