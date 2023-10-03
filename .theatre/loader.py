import logging

import ops
from scenario import Context, State
from charm import TraefikIngressCharm
from unittest.mock import patch, PropertyMock

def patch_all():
    for p in (
            patch("charm.KubernetesServicePatch"),
            patch("lightkube.core.client.GenericSyncClient"),
            patch(
                "charm.TraefikIngressCharm.external_host",
                PropertyMock(return_value="traefik.local")),
            patch(
                "charm.TraefikIngressCharm.version",
                PropertyMock(return_value="42")),
            ):
        p.__enter__()


def charm_context() -> Context:
    """This function is expected to return a ready-to-run ``scenario.Context``.
    Edit this function as necessary.
    """
    patch_all()
    return Context(charm_type=TraefikIngressCharm)
