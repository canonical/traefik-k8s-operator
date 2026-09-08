# Remove Alertmanager from Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every integration-test dependency on `alertmanager-k8s` with the existing `any-charm-k8s` HTTP ingress tester without reducing routing, TLS, restart, or upgrade coverage.

**Architecture:** A module-scoped `ingress_app` fixture deploys one `any-charm-k8s` unit configured by `health_src_overwrite()`. Shared helpers address the generic app through `require-ingress` and verify its `/health` route; standalone suites use the same deployment contract directly.

**Tech Stack:** Python 3.12, pytest, Jubilant, any-charm-k8s, ops, tox, Ruff, Pyright

## Global Constraints

- Keep all existing integration scenarios and assertions that exercise Traefik behavior.
- Remove every `alertmanager-k8s`, `alertmanager_app`, and Alertmanager-specific helper reference from tracked integration-test Python files.
- Use `any-charm-k8s` from the repository-wide `beta` channel constant.
- Relate the any-charm `require-ingress` endpoint to Traefik's `ingress` endpoint.
- Verify the tester through its `/health` endpoint.
- Do not push the branch.

---

## File Structure

- `tests/integration/constants.py`: owns the shared ingress tester application name.
- `tests/integration/conftest.py`: owns the shared any-charm deployment fixture.
- `tests/integration/helpers.py`: owns generic proxied URL lookup and HTTP/HTTPS verification flows.
- `tests/unit/test_integration_test_setup.py`: verifies the fixture deployment contract and URL lookup without Juju.
- `tests/integration/test_dynamic_configs.py`: validates config lifecycle using the generic fixture.
- `tests/integration/test_https_multi_unit.py`: validates HTTPS through all units using the generic fixture.
- `tests/integration/test_pebble_restart_after_cert_relation_joined.py`: deploys any-charm directly for the restart scenario.
- `tests/integration/test_tls.py`: includes any-charm in the multi-application TLS endpoint sweep.
- `tests/integration/test_upgrade.py`: deploys any-charm for the basic upgrade scenario.
- `tests/integration/test_upgrade_*.py`: consumes the renamed shared fixture and generic helper vocabulary.
- `docs/changelog.md`: records the test dependency improvement.
- `docs/release-notes/remove-alertmanager-from-integration-tests.yaml`: provides the required change artifact.

### Task 1: Shared Any-Charm Fixture and URL Contract

**Files:**

- Create: `tests/unit/test_integration_test_setup.py`
- Modify: `tests/integration/constants.py`
- Modify: `tests/integration/conftest.py`
- Modify: `tests/integration/helpers.py`

**Interfaces:**

- Consumes: `ANY_CHARM_CHANNEL`, `ANY_CHARM_K8S`, `PYTHON_PACKAGES`, and `health_src_overwrite() -> str` from `tests.integration.any_charm_helpers`.
- Produces: `INGRESS_APP_NAME = "ingress"`, pytest fixture `ingress_app`, and `_ingress_url(juju: jubilant.Juju) -> str` returning the tester's `/health` URL.

- [ ] **Step 1: Write failing fixture and URL tests**

```python
import json
from unittest.mock import Mock

from tests.integration.any_charm_helpers import (
    ANY_CHARM_CHANNEL,
    ANY_CHARM_K8S,
    PYTHON_PACKAGES,
    health_src_overwrite,
)
from tests.integration.conftest import ingress_fixture
from tests.integration.constants import INGRESS_APP_NAME
from tests.integration.helpers import _ingress_url


def test_ingress_fixture_deploys_health_any_charm():
    juju = Mock()

    result = ingress_fixture.__wrapped__(juju)

    juju.deploy.assert_called_once_with(
        f"ch:{ANY_CHARM_K8S}",
        INGRESS_APP_NAME,
        channel=ANY_CHARM_CHANNEL,
        config={
            "src-overwrite": health_src_overwrite(),
            "python-packages": PYTHON_PACKAGES,
        },
        trust=True,
    )
    assert result == INGRESS_APP_NAME


def test_ingress_url_targets_health_endpoint():
    juju = Mock()
    juju.run.return_value.results = {
        "proxied-endpoints": json.dumps({INGRESS_APP_NAME: {"url": "https://example.test/model-ingress"}})
    }

    assert _ingress_url(juju) == "https://example.test/model-ingress/health"
```

- [ ] **Step 2: Run the tests and verify the missing generic interfaces fail**

Run: `tox -e unit -- tests/unit/test_integration_test_setup.py -q`

Expected: FAIL during collection because `ingress_fixture`, `INGRESS_APP_NAME`, and `_ingress_url` do not exist.

- [ ] **Step 3: Implement the shared fixture and generic URL helper**

Replace `ALERTMANAGER_APP_NAME` with `INGRESS_APP_NAME = "ingress"`. Import the four any-charm helpers in `conftest.py`, rename the fixture to `ingress_app`, and deploy:

```python
juju.deploy(
    f"ch:{ANY_CHARM_K8S}",
    INGRESS_APP_NAME,
    channel=ANY_CHARM_CHANNEL,
    config={
        "src-overwrite": health_src_overwrite(),
        "python-packages": PYTHON_PACKAGES,
    },
    trust=True,
)
```

Rename `_alertmanager_url` to `_ingress_url`, select `endpoints[INGRESS_APP_NAME]["url"]`, and return `f"{url.rstrip('/')}/health"`. Rename helper parameters and local variables from `alertmanager_url` to `ingress_url`. Update composite flow integrations to `f"{INGRESS_APP_NAME}:require-ingress"` and their docstrings to generic ingress terminology.

- [ ] **Step 4: Run the focused tests and verify they pass**

Run: `tox -e unit -- tests/unit/test_integration_test_setup.py -q`

Expected: PASS with 2 tests.

- [ ] **Step 5: Commit the shared contract**

```bash
git add tests/unit/test_integration_test_setup.py tests/integration/constants.py tests/integration/conftest.py tests/integration/helpers.py
git commit -m "test: replace shared alertmanager fixture"
```

### Task 2: Shared Fixture Consumers

**Files:**

- Modify: `tests/integration/test_dynamic_configs.py`
- Modify: `tests/integration/test_https_multi_unit.py`
- Modify: `tests/integration/test_upgrade_mtls_from_280.py`
- Modify: `tests/integration/test_upgrade_mtls_from_280_via_298.py`
- Modify: `tests/integration/test_upgrade_mtls_from_298.py`
- Modify: `tests/integration/test_upgrade_mtls_leader_change_from_298.py`
- Modify: `tests/integration/test_upgrade_mtls_single_unit_from_280.py`
- Modify: `tests/integration/test_upgrade_mtls_single_unit_from_280_via_298.py`
- Modify: `tests/integration/test_upgrade_mtls_single_unit_from_298.py`
- Modify: `tests/integration/test_upgrade_no_tls_from_280.py`
- Modify: `tests/integration/test_upgrade_no_tls_from_280_via_298.py`
- Modify: `tests/integration/test_upgrade_no_tls_from_298.py`
- Modify: `tests/integration/test_upgrade_no_tls_leader_change_from_298.py`
- Modify: `tests/integration/test_upgrade_ssc_from_280.py`
- Modify: `tests/integration/test_upgrade_ssc_from_280_via_298.py`
- Modify: `tests/integration/test_upgrade_ssc_from_298.py`
- Modify: `tests/integration/test_upgrade_ssc_leader_change_from_298.py`
- Modify: `tests/integration/test_upgrade_ssc_single_unit_from_280.py`
- Modify: `tests/integration/test_upgrade_ssc_single_unit_from_280_via_298.py`
- Modify: `tests/integration/test_upgrade_ssc_single_unit_from_298.py`

**Interfaces:**

- Consumes: pytest fixture `ingress_app`; helper APIs from Task 1.
- Produces: unchanged scenario behavior with no Alertmanager-specific fixture vocabulary.

- [ ] **Step 1: Rename every `alertmanager_app` fixture parameter to `ingress_app`**

In dynamic-config and HTTPS tests, integrate `f"{ingress_app}:require-ingress"`. In dynamic-config relation-removal status checks, inspect `status.apps[ingress_app].relations.get("require-ingress", [])`; keep filename prefix assertions based on Traefik's provider endpoint as `juju_ingress_ingress_`.

In all upgrade test signatures, replace `alertmanager_app` with `ingress_app`. Rename URL locals in leader-change tests to `ingress_url`, passing the same value to generic verification helpers.

- [ ] **Step 2: Verify integration modules collect**

Run: `uv run -p 3.12 pytest --collect-only -q tests/integration/test_dynamic_configs.py tests/integration/test_https_multi_unit.py tests/integration/test_upgrade_*.py`

Expected: collection succeeds with no missing fixture errors.

- [ ] **Step 3: Commit shared consumer updates**

```bash
git add tests/integration/test_dynamic_configs.py tests/integration/test_https_multi_unit.py tests/integration/test_upgrade_*.py
git commit -m "test: use any-charm ingress fixture in upgrade tests"
```

### Task 3: Standalone Integration Deployments

**Files:**

- Modify: `tests/integration/test_pebble_restart_after_cert_relation_joined.py`
- Modify: `tests/integration/test_tls.py`
- Modify: `tests/integration/test_upgrade.py`

**Interfaces:**

- Consumes: the any-charm constants and `health_src_overwrite()` deployment contract from Task 1.
- Produces: standalone integration scenarios with no `alertmanager-k8s` deployment.

- [ ] **Step 1: Replace each direct Alertmanager deployment**

Import the any-charm constants and helper, define the local application as `INGRESS_APP = "ingress"`, and deploy the same configuration used by the shared fixture. Relate `f"{INGRESS_APP}:require-ingress"` to Traefik.

In the Pebble-restart test, remove the unrelated certificates relation to the old Alertmanager app and fetch `f"{traefik_url}/{juju.model}-{INGRESS_APP}/health"`.

In the TLS endpoint list, replace the Alertmanager route with `f"{scheme}://{netloc}/{model}-{INGRESS_APP}/health"` while leaving Prometheus and Grafana routes unchanged.

- [ ] **Step 2: Verify standalone modules collect**

Run: `uv run -p 3.12 pytest --collect-only -q tests/integration/test_pebble_restart_after_cert_relation_joined.py tests/integration/test_tls.py tests/integration/test_upgrade.py`

Expected: collection succeeds.

- [ ] **Step 3: Verify Alertmanager is absent from integration Python files**

Run: `if git grep -ni alertmanager -- 'tests/integration/*.py'; then echo 'Unexpected Alertmanager reference found' >&2; exit 1; fi`

Expected: exit 0 with no matches.

- [ ] **Step 4: Commit standalone replacements**

```bash
git add tests/integration/test_pebble_restart_after_cert_relation_joined.py tests/integration/test_tls.py tests/integration/test_upgrade.py
git commit -m "test: remove standalone alertmanager deployments"
```

### Task 4: Documentation and Full Verification

**Files:**

- Modify: `docs/changelog.md`
- Create: `docs/release-notes/remove-alertmanager-from-integration-tests.yaml`

**Interfaces:**

- Consumes: completed integration-test replacement.
- Produces: project-required public change records.

- [ ] **Step 1: Add the changelog entry**

Under `## 2026-09-08`, add:

```markdown
- Replaced the flaky Alertmanager charm in integration tests with an any-charm HTTP ingress tester.
```

- [ ] **Step 2: Add the release-note artifact**

```yaml
version_schema: 2
changes:
- title: Replaced Alertmanager in integration tests
    author: copilot
  type: bugfix
  description: Replaced the flaky Alertmanager test dependency with an any-charm HTTP ingress tester.
  urls:
    related_issue: []
  visibility: internal
  highlight: false
```

- [ ] **Step 3: Run formatting and focused validation**

Run: `tox -e fmt`

Expected: exit 0.

Run: `tox -e unit -- tests/unit/test_integration_test_setup.py -q`

Expected: PASS with 2 tests.

Run: `uv run -p 3.12 pytest --collect-only -q tests/integration`

Expected: collection succeeds.

- [ ] **Step 4: Run repository verification**

Run: `tox -e lint && tox -e static && tox -e unit`

Expected: all environments exit 0.

- [ ] **Step 5: Verify scope and commit**

Run: `git diff --check && if git grep -ni alertmanager -- 'tests/integration/*.py'; then exit 1; fi`

Expected: exit 0 and no Alertmanager matches.

```bash
git add docs/changelog.md docs/release-notes/remove-alertmanager-from-integration-tests.yaml
git commit -m "docs: note any-charm integration test migration"
```
