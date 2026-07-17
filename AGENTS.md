# AGENTS.md

Juju Kubernetes charm (Python 3.12, ops framework) deploying/managing Traefik as an ingress
controller. Uses `tox`/`tox-uv`/`uv`. Line length 99, Google-style docstrings.

## Commands

```shell
tox -e fmt                                                  # auto-format
tox -e lint                                                 # ruff + mypy + pylint
tox -e unit                                                  # unit + scenario tests
tox -e unit -- tests/unit/test_charm.py                     # single file
tox -e unit -- tests/unit/test_charm.py::TestClass::test_x  # single test
tox -e static                                                # pyright + lib LIBPATCH check
tox -e interface                                             # interface tests
tox -e integration                                           # full integration suite (needs live Juju/k8s)
tox -e integration -- tests/integration/test_charm_route.py  # single integration test file
charmcraft pack                                              # build the .charm artifact
```

## Architecture

- `src/charm.py` — `TraefikIngressCharm(CharmBase)`: all Juju event handling, relations, TLS;
  delegates workload ops to `Traefik`.
- `src/traefik.py` — `Traefik`: owns filesystem paths, generates static/dynamic Traefik config,
  manages the Pebble service.
- `src/utils.py` — small helpers (e.g. `is_hostname`).
- `lib/charms/traefik_k8s/` — charm libraries consumed by other charms via `charmcraft fetch-lib`:
  `v2/ingress.py` (per-app, current), `v1/ingress.py` (per-app, legacy), `v1/ingress_per_unit.py`,
  `v0/traefik_route.py` (raw passthrough).

### Design decisions

- **File provider config**: Traefik is configured entirely via YAML files on disk (its
  [File provider](https://doc.traefik.io/traefik/providers/file/)). Dynamic per-relation configs go
  to `/opt/traefik/juju/juju_ingress_*.yaml` (a Juju-managed mounted volume, not the container FS)
  because `inotify` doesn't work in the upstream busybox-based Traefik image — hence the charm uses
  a custom Ubuntu-based image (`docker.io/ubuntu/traefik`). Static config is at
  `/etc/traefik/traefik.yaml`.
- **`flush_dynamic_configs`**: tar-archive push in production; monkey-patched to individual
  `container.push()` calls in tests.
- **Routing modes**: `path` (default) or `subdomain` (`external_hostname` must be a DNS name, not
  an IP, in subdomain mode).
- **Leader-only write-back**: only the leader writes the externally-reachable URL to relation data
  (followers can't write the app databag).
- **Lightkube** does direct k8s API calls (e.g. LoadBalancer service management); always mocked in
  tests.

## Unit/Scenario Tests

- `tests/unit/` — mix of `ops.testing.Harness` (legacy) and `ops-scenario`. Write new tests with
  `ops-scenario`; `Harness` is kept only for existing tests.
- `tests/scenario/` — exclusively `ops-scenario` (`ops-scenario~=6.0`).
- Both run under `tox -e unit`.
- Pattern:
  ```python
  from scenario import Context, State, Container, Relation

  def test_something(traefik_ctx, traefik_container):
      state = State(leader=True, containers=[traefik_container])
      state_out = traefik_ctx.run(traefik_container.pebble_ready_event, state)
      assert state_out.unit_status.name == "active"
  ```
- Shared fixtures (`tests/scenario/conftest.py`, `tests/unit/conftest.py`): `traefik_charm` (patches
  lightkube + `_get_loadbalancer_status`), `traefik_ctx`, `traefik_container` (mounts at `/opt/` and
  `/etc/traefik/`), `mock_lightkube_client` (autouse), `_mock_flush_dynamic_configs` (autouse).
- Harness gotcha: `cached_property` on the charm is per-event in production but persists across
  events in `Harness`. Call `_clear_cached_properties(harness.charm)` after config changes.

## Integration Tests

Use `jubilant` (not `pytest-operator`) against a real Juju/k8s model. CI orchestration uses `opcli`
(from [`canonical/charm-ci`](https://github.com/canonical/charm-ci)) and `spread`.

- **Run locally without spread** (see charm-ci's
  [local-testing guide](https://github.com/canonical/charm-ci#local-testing-without-spread)):
  ```shell
  opcli env provision -c concierge-juju3.yaml   # or concierge-juju4.yaml for Juju 4
  opcli pytest run --suite tests/integration/ -- tests/integration/test_charm_route.py \
    -x --no-juju-teardown --juju-model testing
  ```
  `--no-juju-teardown` keeps the model up for follow-up runs. Without a matching
  `artifacts.build.yaml`, the `traefik_charm` fixture needs a locally-built `.charm`
  (`charmcraft pack`).
- **`spread.yaml`** defines two parallel CI suites over the same auto-discovered modules:
  `tests/integration/` (Juju 3, `concierge-juju3.yaml`) and `tests/integration/juju4/` (Juju 4,
  `concierge-juju4.yaml`). Per-module `BASE/<module>`/`MODULE/<job>`/`CONCIERGE/<job>` overrides pin
  specific tests to a different base or Juju channel (e.g. mTLS/SSC upgrade-from-Charmhub tests
  need `ubuntu@20.04` to match the published source revision's base).
- **`s3-installation.sh`** sets up a local `microceph` RGW (S3-compatible) backend, needed only for
  `test_workload_tracing.py`. Run it (`sudo ./s3-installation.sh`) before that test locally; it runs
  automatically in CI (`prepare:`, no per-test guard).
- **any-charm testers**: tests deploy generic [`any-charm-k8s`](https://charmhub.io/any-charm) with
  custom code injected via `src-overwrite`, from
  `tests/integration/testers/any_charm_src/<name>/any_charm.py` (`ipu`, `tcp_ipu`, `health`, `route`,
  `forward_auth`) to simulate a requirer charm. Fetch relation/interface data (including raw
  databag contents) via the `rpc` Juju action through the shared
  `rpc(juju, unit, method, **kwargs)` helper in `tests/integration/helpers.py` — prefer this over
  parsing `juju show-unit`/`juju status` output.
- **Timing races**: asserting on state right after `juju.wait(all_settled, ...)` can catch a
  transient idle moment mid-handshake (e.g. relation-changed → pebble restart → config file write);
  Juju 4 exposes this more than Juju 3. Require several consecutive idle polls instead of a single
  snapshot: `juju.wait(all_settled, timeout=600, delay=2, successes=5)`.

## Library Versioning

Every file under `lib/charms/` has `LIBAPI`/`LIBPATCH` constants — bump `LIBPATCH` for any change to
a lib file. `tox -e static` enforces this (fails if a lib file differs from `main` without a bump).

## PR Requirements

- Signed commits (GPG/SSH verified) and CLA sign-off required.
- Add a change artifact YAML under `docs/release-notes/` (template:
  `docs/release-notes/template/_change-artifact-template.yaml`); the compliance workflow fails
  without one unless the PR has the `no-release-note` label.
- Add an entry to `docs/changelog.md`.
- PRs are squash-merged onto `main`.
- Disclose AI tool usage in the PR description.
