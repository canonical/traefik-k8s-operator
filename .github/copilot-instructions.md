# Copilot instructions for `traefik-k8s-operator`

## Build, test, and lint

This charm uses `tox` (with `tox-uv`) as the primary entry point for local checks.

```bash
tox -e fmt           # auto-fix formatting with ruff
tox -e lint          # ruff + mypy + pylint
tox -e static        # pyright + library version bump check
tox -e unit          # tests/unit + tests/scenario
tox -e integration   # tests/integration (requires a live Juju/K8s environment)
tox -e interface     # tests/interface
```

Run a single test (or filtered subset) via `tox -e unit -- ...`:

```bash
tox -e unit -- tests/unit/test_charm.py::TestTraefikIngressCharm::test_service_get
tox -e unit -- tests/scenario/test_tls_certificates.py -k test_get_certs
```

Build the charm:

```bash
charmcraft pack
```

Optional local dev shell:

```bash
tox --notest -e unit
source .tox/unit/bin/activate
```

## High-level architecture

- `src/charm.py` (`TraefikIngressCharm`) is the control-plane orchestrator. It wires Juju
  events/relations, reconciles a Kubernetes `LoadBalancer` service via Lightkube, computes ingress
  configs, and drives Pebble restarts.
- `src/traefik.py` (`Traefik`) is the workload interface. It generates/pushes Traefik static and
  dynamic YAML, manages cert/CA files in the container, and encapsulates middleware/router config
  generation for per-app, per-unit, and routed ingress.
- Config flow uses Traefik file provider with:
  - static config at `/etc/traefik/traefik.yaml`
  - dynamic config files at `/opt/traefik/juju/*.yaml` (including per-relation files)
- The charm intentionally uses an Ubuntu-based Traefik image and mounted config volume because the
  upstream busybox image has inotify/file-provider limitations (see README/CONTRIBUTING context).
- Relation surfaces are split between provider and requirer roles:
  - **Provides**: `ingress` (v1/v2), `ingress-per-unit`, `traefik-route`, metrics, dashboards
  - **Requires**: `certificates`, `receive-ca-cert`, `upstream-ingress`, tracing, logging,
    `experimental-forward-auth`
  - **Peer**: `peers` (certificate sharing/state fan-out)

## Key conventions in this repo

- Leader-centric publication is intentional: all units compute routing, but only leader writes
  ingress URLs back to requirers and publishes shared TLS material for peers.
- TLS cert fan-out pattern:
  - leader reads certs from `certificates` relation
  - public cert/CA data is stored in peer app databag
  - private keys are stored in a Juju secret (`TLS_KEY_LABEL`)
  - non-leaders reconstruct certs from peer databag + secret
- `routing_mode` behavior is strict:
  - `path` and `subdomain` are the only valid values
  - `subdomain` requires `external_hostname`
  - when `upstream-ingress` is related, routing mode must be `path`
- Ingress protocol compatibility:
  - `ingress` v2 is the current per-app path
  - `ingress` v1 is still supported as deprecated legacy behavior (per-leader semantics)
  - `ingress-per-unit` supports both HTTP and TCP unit-level configs
- Load balancer annotations come from `config.loadbalancer_annotations` and are Kubernetes-validated
  (`parse_annotations` + key/value validators). Invalid annotation strings prevent LB reconciliation.
- Test suite conventions:
  - `tests/unit/` primarily uses `ops.testing.Harness`
  - `tests/scenario/` uses `ops-scenario` (`Context`/`State`)
  - scenario fixtures patch tracing and Lightkube/LB status in `tests/*/conftest.py`; follow those
    patterns when adding scenario tests.
- Import/runtime path convention:
  - `tox` sets `PYTHONPATH` to repo root + `lib` + `src`
  - charm runtime imports assume `src/` as root (use imports like `from charm import ...`)
- Tooling targets Python 3.8 and a 99-char line length (`ruff`, `black`, `mypy`, `pyright`).
- `pydantic>=2` is required; `charm.py` has a compatibility gate (`PYDANTIC_IS_V1`) for older
  runtime environments.
- If you modify interface libraries under `lib/charms/traefik_k8s/v*/`, bump `LIBPATCH` (or
  `LIBAPI` for breaking changes). `tox -e static` enforces this against `main`.
