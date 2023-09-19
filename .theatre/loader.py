from unittest.mock import PropertyMock, patch

from scenario import Context, State, Container

from charm import TraefikIngressCharm


def patch_all():
    for p in [
        patch("charm.KubernetesServicePatch"),
        patch("lightkube.core.client.GenericSyncClient"),
        patch("charm.TraefikIngressCharm.external_host",
              PropertyMock(return_value="testhostname"))
    ]:
        p.__enter__()


def charm_context() -> Context:
    """This function is expected to return a ready-to-run ``scenario.Context``.
    Edit this function as necessary.
    """
    patch_all()
    return Context(
        charm_type=TraefikIngressCharm
    )
