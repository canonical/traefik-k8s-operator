# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
import os
import subprocess
from pathlib import Path
from typing import cast

import jubilant
import pytest
import yaml

from tests.integration.helpers import all_settled

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

ALERTMANAGER_APP_NAME = "alertmanager"
TRAEFIK_APP_NAME = "traefik"

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


@pytest.fixture(scope="module", name="traefik_app")
def deploy_traefik(juju, traefik_charm):
    """Deploy traefik."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": "traefik-demo.local"})
    juju.wait(all_settled, delay=5, timeout=600)
    return TRAEFIK_APP_NAME


@pytest.fixture(scope="module", name="alertmanager_app")
def alertmanager_fixture(juju, traefik_app):
    """Deploy alertmanager and integrate with traefik."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(jubilant.all_active, timeout=600)
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", traefik_app)
    juju.wait(jubilant.all_active, timeout=600)
    return ALERTMANAGER_APP_NAME


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
