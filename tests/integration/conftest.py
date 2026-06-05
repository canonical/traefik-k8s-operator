# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import subprocess
from pathlib import Path
from typing import cast

import jubilant
import pytest

logger = logging.getLogger(__name__)


@pytest.fixture(scope="module")
def traefik_charm():
    charm_path = os.environ.get("CHARM_PATH")
    if charm_path:
        return Path(charm_path).resolve()
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


@pytest.fixture(scope="module", name="juju")
def juju_fixture(request):
    """Jubilant Juju fixture.

    Honours ``--model`` (use a pre-existing model, e.g. the one bootstrapped by
    concierge in CI) and ``--keep-models`` (preserve the temp model on failure).
    """
    model = request.config.getoption("--model")
    if model:
        _juju = jubilant.Juju(model=model)
        _juju.wait_timeout = 10 * 60
        _grant_secret_rbac(model)
        yield _juju
        return

    keep_models = cast(bool, request.config.getoption("--keep-models"))
    with jubilant.temp_model(keep=keep_models) as _juju:
        _juju.wait_timeout = 10 * 60
        yield _juju


def _grant_secret_rbac(namespace: str) -> None:
    """Pre-grant secret RBAC permissions in the model namespace.

    On Juju 4 + canonical k8s, Juju creates ``juju-secret-consumer-*`` service
    accounts with per-SA Role/RoleBinding scoped to specific secret names.
    However, these bindings consistently fail to take effect (even after 2+
    minutes of retries), causing hooks that consume secrets to error out.

    The root cause appears to be that canonical k8s does not correctly evaluate
    ``apiGroups: ["*"]`` + ``resourceNames: [specific-name]`` role rules for
    the core API group secrets resource.

    As a workaround we pre-create a permissive Role + RoleBinding that grants
    all service accounts in the namespace the ability to manage secrets.  This
    is safe because the namespace is a throwaway test environment.
    """
    manifest = f"""\
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: juju-secret-access
  namespace: {namespace}
rules:
- apiGroups: [""]
  resources: ["secrets"]
  verbs: ["get", "list", "create", "patch", "update", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: juju-secret-access
  namespace: {namespace}
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: Role
  name: juju-secret-access
subjects:
- kind: Group
  name: system:serviceaccounts:{namespace}
  apiGroup: rbac.authorization.k8s.io
"""
    result = subprocess.run(
        ["kubectl", "apply", "-f", "-"],
        input=manifest,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        logger.warning("Could not pre-grant secret RBAC (kubectl not available?): %s", result.stderr)
    else:
        logger.info("Pre-granted secret RBAC in namespace %r", namespace)


@pytest.fixture(autouse=True, scope="module")
def copy_traefik_library_into_tester_charms():
    """No-op: jubilant tests deploy from Charmhub, not local tester charms."""


@pytest.fixture(autouse=True, scope="module")
async def setup_env():
    """No-op: jubilant tests manage their own model via jubilant."""
