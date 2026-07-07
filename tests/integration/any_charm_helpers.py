# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers to deploy any-charm / any-charm-k8s as tester charms.

Instead of building local tester charms, we deploy any-charm from charmhub and
configure it via `src-overwrite` to run the equivalent charm code.

The actual charm source lives in tests/integration/testers/any_charm_src/<name>/
so that IDEs can lint and highlight it properly.

NOTE: any-charm's src_overwrite() only creates one level of parent directories.
Therefore, library files are shipped with flat key names (e.g. `_lib_ingress_v2.py`)
and each any_charm.py bootstraps the proper nested package structure at import time.
"""

import json
from pathlib import Path

LIB_ROOT = Path(__file__).parent.parent.parent / "lib" / "charms"
SRC_ROOT = Path(__file__).parent / "testers" / "any_charm_src"

# Mapping from flat src-overwrite key -> actual library file on disk.
_TRAEFIK_LIBS = {
    "_lib_ingress_v2.py": LIB_ROOT / "traefik_k8s" / "v2" / "ingress.py",
    "_lib_ingress_per_unit_v1.py": LIB_ROOT / "traefik_k8s" / "v1" / "ingress_per_unit.py",
    "_lib_traefik_route_v0.py": LIB_ROOT / "traefik_k8s" / "v0" / "traefik_route.py",
}

# The oathkeeper auth_proxy library for forward-auth tests.
_OATHKEEPER_LIB = (
    SRC_ROOT / "forward_auth" / "charms" / "oathkeeper" / "v0" / "auth_proxy.py"
)

# Python packages required by the traefik libs inside any-charm.
PYTHON_PACKAGES = "pydantic>=2\ncryptography\njsonschema"

# any-charm channel to use
ANY_CHARM_CHANNEL = "beta"

# For k8s charms that need a container
ANY_CHARM_K8S = "any-charm-k8s"
# For machine charms or charms without container needs
ANY_CHARM = "any-charm"


def _read_libs(*lib_keys: str) -> dict:
    """Read the specified library files and return them as a dict for src-overwrite."""
    result = {}
    for key in lib_keys:
        result[key] = _TRAEFIK_LIBS[key].read_text(encoding="utf-8")
    return result


def _read_src_files(tester_name: str, filenames: list[str]) -> dict:
    """Read source files from the any_charm_src/<tester_name>/ directory."""
    result = {}
    for filename in filenames:
        result[filename] = (SRC_ROOT / tester_name / filename).read_text(encoding="utf-8")
    return result


def ipa_src_overwrite() -> str:
    """Generate src-overwrite config for a simple ingress-per-app requirer."""
    files = _read_libs("_lib_ingress_v2.py")
    files.update(_read_src_files("ipa", ["any_charm.py"]))
    return json.dumps(files)


def ipu_src_overwrite() -> str:
    """Generate src-overwrite config for a simple ingress-per-unit requirer."""
    files = _read_libs("_lib_ingress_per_unit_v1.py")
    files.update(_read_src_files("ipu", ["any_charm.py"]))
    return json.dumps(files)


def tcp_ipu_src_overwrite() -> str:
    """Generate src-overwrite config for a TCP ingress-per-unit requirer."""
    files = _read_libs("_lib_ingress_per_unit_v1.py")
    files.update(_read_src_files("tcp_ipu", ["any_charm.py"]))
    return json.dumps(files)


def route_src_overwrite() -> str:
    """Generate src-overwrite config for a traefik-route requirer."""
    files = _read_libs("_lib_traefik_route_v0.py")
    files.update(_read_src_files("route", ["any_charm.py"]))
    return json.dumps(files)


def forward_auth_src_overwrite() -> str:
    """Generate src-overwrite config for the IAP requirer (forward-auth tester)."""
    files = _read_libs("_lib_ingress_v2.py")
    files["_lib_auth_proxy_v0.py"] = _OATHKEEPER_LIB.read_text(encoding="utf-8")
    files.update(_read_src_files("forward_auth", ["any_charm.py", "httpbin_server.py"]))
    return json.dumps(files)


def health_src_overwrite() -> str:
    """Generate src-overwrite config for the health tester."""
    files = _read_libs("_lib_ingress_v2.py")
    files.update(_read_src_files("health", ["any_charm.py", "health_server.py"]))
    return json.dumps(files)

