# Reduce Duplicate Integration Tests Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the one integration test proven redundant by audit (`test_upgrade.py`), and eliminate the duplicated boilerplate across the `test_upgrade_{no_tls,ssc,mtls}_from_{280,298}.py` / `*_single_unit_from_{280,298}.py` file pairs by extracting each pair's identical body into a single shared, revision-parametrized helper function — without changing which test files exist, which test scenarios run, or the CI job matrix.

**Architecture:** All new shared logic lives in `tests/integration/helpers.py` (already the home of the `bring_up_*`/`verify_*` composite-flow helpers these tests already call). Each of the 10 existing "from revision N" test files becomes a thin wrapper: it keeps its own filename (required — `spread.yaml` references these files by path for CI's `BASE`/`MODULE` overrides), its own test function name and docstring (for readability/log clarity), and its own `SOURCE_REVISION` constant, but delegates the actual deploy → verify → refresh → verify body to one new shared helper per family.

**Tech Stack:** Python 3.12, pytest, jubilant (Juju test harness), tox/uv.

## Global Constraints

- Do not change: test file paths, test function names/node IDs, `spread.yaml` job matrix (except removing the 2 dead lines for the deleted file), or any assertion's pass/fail behavior. Coverage must be identical before and after.
- Line length 99 (ruff/black-style, per `pyproject.toml`).
- `tests/integration/helpers.py` currently has no unit tests of its own (integration tests need a live Juju/k8s model); validate changes via `tox -e lint` (ruff over `tests/`) and `tox -e integration -- --collect-only <files>` (proven to work without a live model — it only imports modules and collects pytest node IDs).
- Per `AGENTS.md` PR requirements: add a changelog entry under `docs/changelog.md` and a change-artifact YAML under `docs/release-notes/artifacts/` before finishing.
- This work happens in the current worktree/branch (`agents/reduce-duplicate-integration-tests`, already rebased onto `main`). Do not touch the other checked-out worktree.

---

### Task 1: Remove the redundant `test_upgrade.py` smoke test

**Why:** Audit (git history + line-by-line comparison) showed `tests/integration/test_upgrade.py` (added in PR #722) deploys Traefik from the unpinned `latest/edge` channel, refreshes to the local build, and asserts only the revision changed — it performs **no HTTP/HTTPS connectivity check at all**. `tests/integration/test_upgrade_ssc_from_298.py` (added two weeks later in PR #729) covers the exact same scenario (deploy old + SSC + ingress requirer, refresh to local build) on a pinned, deterministic revision, with 3 units, and with explicit `verify_https_on_all_units` checks both before and after the refresh. `test_upgrade.py` adds no coverage beyond what `test_upgrade_ssc_from_298.py` already exceeds.

**Files:**
- Delete: `tests/integration/test_upgrade.py`
- Modify: `spread.yaml:41-42`

**Interfaces:** None (pure deletion, no other file imports from `test_upgrade.py`).

- [ ] **Step 1: Delete the file**

```bash
git rm tests/integration/test_upgrade.py
```

- [ ] **Step 2: Remove its now-dead spread.yaml entries**

In `spread.yaml`, remove these two lines from the `tests/integration/` suite's `environment:` block (currently lines 41-42, immediately after the `BASE/jubilant_test_charm_ipa_2004` / `MODULE/jubilant_test_charm_ipa_2004` pair and before the "Manual-TLS upgrade tests" comment):

```yaml
      BASE/jubilant_test_upgrade_2004: ubuntu@20.04
      MODULE/jubilant_test_upgrade_2004: tests/integration/test_upgrade.py
```

- [ ] **Step 3: Verify no other references remain**

```bash
grep -rn "test_upgrade\.py" --include=*.yaml --include=*.yml --include=*.md .
```
Expected: no output (empty).

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test: remove redundant test_upgrade.py smoke test

Superseded by test_upgrade_ssc_from_298.py, which covers the same
scenario (old revision + SSC + ingress requirer, refresh to local
build) with a pinned revision, 3 units, and explicit HTTPS
connectivity checks that test_upgrade.py never performed."
```

---

### Task 2: Add five shared upgrade-scenario helper functions to `helpers.py`

**Files:**
- Modify: `tests/integration/helpers.py:25-31` (import block)
- Modify: `tests/integration/helpers.py:507-547` (append after existing `bring_up_*` composite-flow functions, in the `# --- Composite flows ---` section)

**Interfaces:**
- Consumes (already defined earlier in `helpers.py`): `all_settled(status) -> bool`, `assert_traefik_revision(juju, expected_revision: int) -> None`, `bring_up_traefik_without_certificate_provider(juju) -> str`, `bring_up_self_signed_traefik(juju, tmp_path) -> str`, `bring_up_certified_traefik(juju, tmp_path) -> str`, `verify_http_on_all_units(juju, expected_url=None) -> str`, `verify_https_on_all_units(juju, expected_url=None) -> str`, `verify_https_on_unit(juju, unit_name, ingress_url) -> None`, `get_outstanding_csrs(juju) -> List[dict]`.
- Produces (new, consumed by Tasks 3-7): `run_no_tls_upgrade_scenario`, `run_ssc_upgrade_scenario`, `run_ssc_single_unit_upgrade_scenario`, `run_mtls_upgrade_scenario`, `run_mtls_single_unit_upgrade_scenario` — exact signatures below.

- [ ] **Step 1: Extend the `constants` import**

In `tests/integration/helpers.py`, the import block at lines 25-31 currently reads:

```python
from constants import (
    INGRESS_REQUIRER_APP_NAME,
    MANUAL_TLS_APP_NAME,
    MOCK_HOSTNAME,
    SSC_APP_NAME,
    TRAEFIK_APP_NAME,
)
```

Replace it with:

```python
from constants import (
    INGRESS_REQUIRER_APP_NAME,
    MANUAL_TLS_APP_NAME,
    MOCK_HOSTNAME,
    NUM_TRAEFIK_UNITS,
    SOURCE_CHANNEL,
    SSC_APP_NAME,
    TRAEFIK_APP_NAME,
    TRAEFIK_CHARM,
)
```

- [ ] **Step 2: Append the five shared scenario helpers**

At the end of `tests/integration/helpers.py` (after the existing `bring_up_traefik_without_certificate_provider` function, which currently ends the file), add:

```python


def run_no_tls_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with no cert provider, then upgrade it.

    Verifies the ingress URL stays reachable over HTTP on every unit both before
    and after refreshing to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_traefik_without_certificate_provider(juju)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_http_on_all_units(juju, expected_url=url)


def run_ssc_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with self-signed certs, then upgrade it.

    Verifies HTTPS stays reachable on every unit both before and after refreshing
    to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_self_signed_traefik(juju, tmp_path)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_all_units(juju, expected_url=url)


def run_ssc_single_unit_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy a single-unit traefik at *source_revision* with self-signed certs, then upgrade it.

    Verifies HTTPS stays reachable on the single unit both before and after
    refreshing to the locally built charm.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_self_signed_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)


def run_mtls_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy traefik at *source_revision* with manual TLS certs, then upgrade it.

    Verifies the migrated key still matches the certificate on every unit and
    that no new certificate request was raised by the upgrade.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        num_units=NUM_TRAEFIK_UNITS,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_all_units(juju, expected_url=url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )


def run_mtls_single_unit_upgrade_scenario(
    juju: jubilant.Juju,
    traefik_charm,
    traefik_resources: dict,
    tmp_path: Path,
    source_revision: int,
) -> None:
    """Deploy a single-unit traefik at *source_revision* with manual TLS certs, then upgrade it.

    Verifies the migrated key still matches the certificate on the single unit
    and that no new certificate request was raised by the upgrade.
    """
    juju.deploy(
        TRAEFIK_CHARM,
        TRAEFIK_APP_NAME,
        channel=SOURCE_CHANNEL,
        config={"external_hostname": MOCK_HOSTNAME},
        revision=source_revision,
        trust=True,
    )
    juju.wait(jubilant.all_agents_idle, error=jubilant.any_error, timeout=900, delay=5, successes=5)
    url = bring_up_certified_traefik(juju, tmp_path)
    unit_name = next(iter(juju.status().apps[TRAEFIK_APP_NAME].units))

    juju.refresh(TRAEFIK_APP_NAME, path=traefik_charm, resources=traefik_resources)
    juju.wait(all_settled, error=jubilant.any_error, delay=5, timeout=900, successes=5)
    assert_traefik_revision(juju, 0)

    verify_https_on_unit(juju, unit_name, url)
    assert len(get_outstanding_csrs(juju)) == 0, (
        "manual-tls-certificates has outstanding requests after upgrade; "
        "the TLS private key was not reused during migration"
    )
```

- [ ] **Step 3: Lint**

```bash
tox -e lint -- tests/integration/helpers.py
```
Expected: no ruff errors (unused-import etc.). It's expected/fine that `run_*` functions are reported as unused at this point if pylint were run on this file, but pylint only checks `src_path` per `tox.ini`, so this won't fire.

- [ ] **Step 4: Commit**

```bash
git add tests/integration/helpers.py
git commit -m "test: add shared upgrade-scenario helpers

Extracts the deploy -> verify -> refresh -> verify body shared by
the *_from_280.py / *_from_298.py upgrade-test pairs into five
revision-parametrized helpers, so the pairs can stop duplicating it
verbatim."
```

---

### Task 3: Refactor the no-TLS upgrade pair to use the shared helper

**Files:**
- Modify: `tests/integration/test_upgrade_no_tls_from_280.py` (full rewrite)
- Modify: `tests/integration/test_upgrade_no_tls_from_298.py` (full rewrite)

**Interfaces:**
- Consumes: `run_no_tls_upgrade_scenario(juju, traefik_charm, traefik_resources, source_revision)` from Task 2.

- [ ] **Step 1: Rewrite `test_upgrade_no_tls_from_280.py`**

Replace the entire file with:

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik without a certificate provider from Charmhub revision 280.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate only with
    an ingress requirer (no certificate provider relation).
2. Verify the ingress URL is reachable over HTTP through every traefik unit
   and all units are active / idle.
3. Refresh traefik to the locally built charm.
4. Verify the same HTTP URL remains reachable on every unit and no unit is
   blocked/error.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_no_tls_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_no_tls_from_revision_280(juju: jubilant.Juju, traefik_charm, ingress_app):
    """Traefik stays healthy and serves HTTP after upgrading from rev 280."""
    run_no_tls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, SOURCE_REVISION)
```

- [ ] **Step 2: Rewrite `test_upgrade_no_tls_from_298.py`**

Replace the entire file with:

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik without a certificate provider from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate only with
    an ingress requirer (no certificate provider relation).
2. Verify the ingress URL is reachable over HTTP through every traefik unit
   while no unit enters blocked/error.
3. Refresh traefik to the locally built charm.
4. Verify the same HTTP URL remains reachable on every unit and no unit is
   blocked/error.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_no_tls_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_no_tls_from_revision_298(juju: jubilant.Juju, traefik_charm, ingress_app):
    """Traefik stays healthy and serves HTTP after upgrading from rev 298."""
    run_no_tls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, SOURCE_REVISION)
```

- [ ] **Step 3: Verify collection (no live Juju model needed)**

```bash
tox -e integration -- --collect-only tests/integration/test_upgrade_no_tls_from_280.py tests/integration/test_upgrade_no_tls_from_298.py
```
Expected: `collected 2 items`, listing `test_upgrade_no_tls_from_revision_280` and `test_upgrade_no_tls_from_revision_298` — same node IDs as before the refactor.

- [ ] **Step 4: Lint**

```bash
tox -e lint -- tests/integration/test_upgrade_no_tls_from_280.py tests/integration/test_upgrade_no_tls_from_298.py
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_upgrade_no_tls_from_280.py tests/integration/test_upgrade_no_tls_from_298.py
git commit -m "test: dedupe no-tls upgrade test pair via shared helper"
```

---

### Task 4: Refactor the SSC (self-signed certs, multi-unit) upgrade pair

**Files:**
- Modify: `tests/integration/test_upgrade_ssc_from_280.py` (full rewrite)
- Modify: `tests/integration/test_upgrade_ssc_from_298.py` (full rewrite)

**Interfaces:**
- Consumes: `run_ssc_upgrade_scenario(juju, traefik_charm, traefik_resources, tmp_path, source_revision)` from Task 2.

- [ ] **Step 1: Rewrite `test_upgrade_ssc_from_280.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik with self-signed certificates from Charmhub revision 280.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate it with
    ``self-signed-certificates`` and an ingress requirer.
2. Verify the ingress URL is reachable over HTTPS through every traefik unit.
3. Refresh traefik to the locally built charm.
4. Verify the same CA still serves the same URL on every unit.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_ssc_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_ssc_from_revision_280(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """Traefik keeps serving HTTPS after upgrading from rev 280 with self-signed certs."""
    run_ssc_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
```

- [ ] **Step 2: Rewrite `test_upgrade_ssc_from_298.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik with self-signed certificates from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
    ``self-signed-certificates`` and an ingress requirer.
2. Verify the ingress URL is reachable over HTTPS through every traefik unit.
3. Refresh traefik to the locally built charm.
4. Verify the same CA still serves the same URL on every unit.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_ssc_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_from_revision_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """Traefik keeps serving HTTPS after upgrading from rev 298 with self-signed certs."""
    run_ssc_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
```

- [ ] **Step 3: Verify collection**

```bash
tox -e integration -- --collect-only tests/integration/test_upgrade_ssc_from_280.py tests/integration/test_upgrade_ssc_from_298.py
```
Expected: `collected 2 items`.

- [ ] **Step 4: Lint**

```bash
tox -e lint -- tests/integration/test_upgrade_ssc_from_280.py tests/integration/test_upgrade_ssc_from_298.py
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_upgrade_ssc_from_280.py tests/integration/test_upgrade_ssc_from_298.py
git commit -m "test: dedupe ssc upgrade test pair via shared helper"
```

---

### Task 5: Refactor the SSC single-unit upgrade pair

**Files:**
- Modify: `tests/integration/test_upgrade_ssc_single_unit_from_280.py` (full rewrite)
- Modify: `tests/integration/test_upgrade_ssc_single_unit_from_298.py` (full rewrite)

**Interfaces:**
- Consumes: `run_ssc_single_unit_upgrade_scenario(juju, traefik_charm, traefik_resources, tmp_path, source_revision)` from Task 2.

- [ ] **Step 1: Rewrite `test_upgrade_ssc_single_unit_from_280.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment with self-signed certificates from revision 280."""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_ssc_single_unit_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_ssc_single_unit_from_280(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """A single traefik unit keeps serving HTTPS after upgrading from rev 280."""
    run_ssc_single_unit_upgrade_scenario(
        juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION
    )
```

- [ ] **Step 2: Rewrite `test_upgrade_ssc_single_unit_from_298.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment with self-signed certificates from revision 298."""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_ssc_single_unit_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_ssc_single_unit_from_298(
    juju: jubilant.Juju, traefik_charm, ssc_app, ingress_app, tmp_path
):
    """A single traefik unit keeps serving HTTPS after upgrading from rev 298."""
    run_ssc_single_unit_upgrade_scenario(
        juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION
    )
```

- [ ] **Step 3: Verify collection**

```bash
tox -e integration -- --collect-only tests/integration/test_upgrade_ssc_single_unit_from_280.py tests/integration/test_upgrade_ssc_single_unit_from_298.py
```
Expected: `collected 2 items`.

- [ ] **Step 4: Lint**

```bash
tox -e lint -- tests/integration/test_upgrade_ssc_single_unit_from_280.py tests/integration/test_upgrade_ssc_single_unit_from_298.py
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_upgrade_ssc_single_unit_from_280.py tests/integration/test_upgrade_ssc_single_unit_from_298.py
git commit -m "test: dedupe ssc single-unit upgrade test pair via shared helper"
```

---

### Task 6: Refactor the mTLS (multi-unit) upgrade pair

**Files:**
- Modify: `tests/integration/test_upgrade_mtls_from_280.py` (full rewrite)
- Modify: `tests/integration/test_upgrade_mtls_from_298.py` (full rewrite)

**Interfaces:**
- Consumes: `run_mtls_upgrade_scenario(juju, traefik_charm, traefik_resources, tmp_path, source_revision)` from Task 2.

- [ ] **Step 1: Rewrite `test_upgrade_mtls_from_280.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik from Charmhub revision 280 to the charm under test.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 280 and integrate it with
    ``manual-tls-certificates`` and an ingress requirer.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through every traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL on every unit and
   that the manual-tls charm has no outstanding certificate requests.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_mtls_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_mtls_from_revision_280(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """Traefik keeps serving the same certificate after upgrading from rev 280."""
    run_mtls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
```

- [ ] **Step 2: Rewrite `test_upgrade_mtls_from_298.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade traefik from Charmhub revision 298 to the charm under test.

Scenario:

1. Deploy traefik-k8s (3 units) at revision 298 and integrate it with
    ``manual-tls-certificates`` and an ingress requirer.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through every traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL on every unit and
   that the manual-tls charm has no outstanding certificate requests.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_mtls_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_mtls_from_revision_298(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """Traefik keeps serving the same certificate after upgrading from rev 298."""
    run_mtls_upgrade_scenario(juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION)
```

- [ ] **Step 3: Verify collection**

```bash
tox -e integration -- --collect-only tests/integration/test_upgrade_mtls_from_280.py tests/integration/test_upgrade_mtls_from_298.py
```
Expected: `collected 2 items`.

- [ ] **Step 4: Lint**

```bash
tox -e lint -- tests/integration/test_upgrade_mtls_from_280.py tests/integration/test_upgrade_mtls_from_298.py
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_upgrade_mtls_from_280.py tests/integration/test_upgrade_mtls_from_298.py
git commit -m "test: dedupe mtls upgrade test pair via shared helper"
```

---

### Task 7: Refactor the mTLS single-unit upgrade pair

**Files:**
- Modify: `tests/integration/test_upgrade_mtls_single_unit_from_280.py` (full rewrite)
- Modify: `tests/integration/test_upgrade_mtls_single_unit_from_298.py` (full rewrite)

**Interfaces:**
- Consumes: `run_mtls_single_unit_upgrade_scenario(juju, traefik_charm, traefik_resources, tmp_path, source_revision)` from Task 2.

- [ ] **Step 1: Rewrite `test_upgrade_mtls_single_unit_from_280.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment from Charmhub revision 280.

Scenario:

1. Deploy traefik-k8s (1 unit) at revision 280 and integrate it with
    ``manual-tls-certificates`` and an ingress requirer.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through the single traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL and that the
   manual-tls charm has no outstanding certificate requests.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_mtls_single_unit_upgrade_scenario

SOURCE_REVISION = 280


@pytest.mark.setup
def test_upgrade_mtls_single_unit_from_280(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """A single traefik unit keeps serving the same certificate after upgrading from rev 280."""
    run_mtls_single_unit_upgrade_scenario(
        juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION
    )
```

- [ ] **Step 2: Rewrite `test_upgrade_mtls_single_unit_from_298.py`**

```python
#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Upgrade a single-unit traefik deployment from Charmhub revision 298.

Scenario:

1. Deploy traefik-k8s (1 unit) at revision 298 and integrate it with
    ``manual-tls-certificates`` and an ingress requirer.
2. Sign every outstanding CSR and provide the certificate back to traefik.
3. Verify the ingress URL is reachable over HTTPS through the single traefik unit.
4. Refresh traefik to the locally built charm.
5. Verify the *same* certificate still serves the *same* URL and that the
   manual-tls charm has no outstanding certificate requests.
"""

import jubilant
import pytest
from conftest import TRAEFIK_RESOURCES
from helpers import run_mtls_single_unit_upgrade_scenario

SOURCE_REVISION = 298


@pytest.mark.setup
def test_upgrade_mtls_single_unit_from_298(
    juju: jubilant.Juju, traefik_charm, mtls_app, ingress_app, tmp_path
):
    """A single traefik unit keeps serving the same certificate after upgrading from rev 298."""
    run_mtls_single_unit_upgrade_scenario(
        juju, traefik_charm, TRAEFIK_RESOURCES, tmp_path, SOURCE_REVISION
    )
```

- [ ] **Step 3: Verify collection**

```bash
tox -e integration -- --collect-only tests/integration/test_upgrade_mtls_single_unit_from_280.py tests/integration/test_upgrade_mtls_single_unit_from_298.py
```
Expected: `collected 2 items`.

- [ ] **Step 4: Lint**

```bash
tox -e lint -- tests/integration/test_upgrade_mtls_single_unit_from_280.py tests/integration/test_upgrade_mtls_single_unit_from_298.py
```
Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_upgrade_mtls_single_unit_from_280.py tests/integration/test_upgrade_mtls_single_unit_from_298.py
git commit -m "test: dedupe mtls single-unit upgrade test pair via shared helper"
```

---

### Task 8: Full-suite verification, changelog, and release-note artifact

**Files:**
- Modify: `docs/changelog.md`
- Create: `docs/release-notes/artifacts/pr_reduce_integration_test_duplication.yaml`

**Interfaces:** None (documentation + final verification only).

- [ ] **Step 1: Collect the entire integration suite to confirm nothing else broke**

```bash
tox -e integration -- --collect-only
```
Expected: collection succeeds (no import errors) and the total collected-test count is exactly 1 lower than before this plan started (the removed `test_upgrade` test), with every other previously-collected node ID (function name) still present and unchanged. To compare precisely:

```bash
git stash
tox -e integration -- --collect-only -q | grep "::" | sort > /tmp/before.txt
git stash pop
tox -e integration -- --collect-only -q | grep "::" | sort > /tmp/after.txt
diff /tmp/before.txt /tmp/after.txt
```
Expected `diff` output: only one removed line, `tests/integration/test_upgrade.py::test_upgrade`; no other lines added or removed.

- [ ] **Step 2: Full lint pass**

```bash
tox -e lint
```
Expected: passes (ruff/mypy/pylint all clean, same as before this change since only `tests/integration/` files were touched and mypy/pylint don't scan that directory).

- [ ] **Step 3: Add the changelog entry**

In `docs/changelog.md`, add a new section right after the `# Changelog` intro/before the existing `## 2026-09-08` entry:

```markdown
## 2026-09-09

- Removed the redundant `test_upgrade.py` integration test (fully superseded by `test_upgrade_ssc_from_298.py`) and deduplicated the boilerplate shared by the revision-pinned upgrade integration tests into shared helper functions.
```

- [ ] **Step 4: Add the release-note change artifact**

Create `docs/release-notes/artifacts/pr_reduce_integration_test_duplication.yaml`:

```yaml
# Version of the artifact schema
version_schema: 2

changes:
  - title: Reduced duplication in the integration test suite
    author: <your-github-username>
    type: minor
    description: |
      Removed test_upgrade.py, an integration test fully superseded by the more
      rigorous test_upgrade_ssc_from_298.py, and extracted the boilerplate shared
      by the revision-pinned upgrade integration test pairs (no-tls, self-signed
      certs, and manual-tls, each in multi-unit and single-unit variants) into
      shared helper functions in tests/integration/helpers.py. No test coverage
      or CI job matrix changed.
    urls:
      pr:
        - "" # fill in once the PR is opened
    visibility: internal
    highlight: false
```

Note: fill in the `pr:` URL once this branch's pull request is opened (this is the same two-step pattern used by the existing `docs/release-notes/artifacts/pr0775.yaml` et al. — the artifact is authored alongside the code change, and the PR URL is the one piece that cannot exist before the PR does).

- [ ] **Step 5: Commit**

```bash
git add docs/changelog.md docs/release-notes/artifacts/pr_reduce_integration_test_duplication.yaml
git commit -m "docs: add changelog entry and release-note artifact for test dedup"
```

---

## Self-Review Notes

- **Spec coverage:** Task 1 removes the one audited no-coverage-loss duplicate. Tasks 2-7 DRY-refactor all 5 exact-duplicate file pairs identified by the automated pairwise-similarity scan (ratio 1.000: no_tls, ssc, mtls, ssc single-unit, mtls single-unit). The other near-duplicate files found during the audit (`test_upgrade_*_leader_change_from_298.py`, `test_upgrade_*_from_280_via_298.py`, `test_https_multi_unit.py`, `test_tcp_ipa/ipu_compatibility.py`, `test_charm_ipa.py`/`test_charm_ipu.py`) were deliberately left untouched — each was confirmed to test a distinct, non-formulaic regression/topology/CI-suite concern (see conversation history), and forcing them through a shared helper would either lose their bespoke assertions or require an over-parametrized helper that hurts readability for no coverage benefit.
- **No placeholders:** The only unavoidable placeholder is the `pr:` URL in the release-note artifact (Task 8), which cannot exist before the PR is opened — the same pattern the repo's own existing artifacts follow.
- **Type/name consistency:** Verified every new helper function name and parameter order is used identically at every call site across Tasks 3-7.
