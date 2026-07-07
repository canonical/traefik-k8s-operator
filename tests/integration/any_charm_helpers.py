# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helpers to deploy any-charm / any-charm-k8s as tester charms.

Instead of building local tester charms, we deploy any-charm from charmhub and
configure it via `src-overwrite` to run the equivalent charm code.

The actual charm source lives in tests/integration/testers/any_charm_src/<name>/
so that IDEs can lint and highlight it properly.

NOTE: any-charm's src_overwrite() only creates one level of parent directories.
We work around this by including __init__.py entries in order so each level gets
created before deeper files are written.
"""

import json
from collections import OrderedDict
from pathlib import Path

LIB_ROOT = Path(__file__).parent.parent.parent / "lib" / "charms"
SRC_ROOT = Path(__file__).parent / "testers" / "any_charm_src"

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


def _lib_files(lib_path: str, source: Path) -> OrderedDict:
    """Return an ordered dict with __init__.py stubs and the lib file itself.

    The entries are ordered so that any-charm's src_overwrite() creates each
    parent directory before attempting to write deeper files.
    """
    parts = Path(lib_path).parts  # e.g. ('charms', 'traefik_k8s', 'v2', 'ingress.py')
    files = OrderedDict()
    # Create __init__.py for each intermediate package directory
    for i in range(1, len(parts)):
        init_path = str(Path(*parts[:i]) / "__init__.py")
        files[init_path] = ""
    # Then the actual library file
    files[lib_path] = source.read_text(encoding="utf-8")
    return files


def _read_src_files(tester_name: str, filenames: list[str]) -> dict:
    """Read source files from the any_charm_src/<tester_name>/ directory."""
    result = {}
    for filename in filenames:
        result[filename] = (SRC_ROOT / tester_name / filename).read_text(encoding="utf-8")
    return result


def ipa_src_overwrite() -> str:
    """Generate src-overwrite config for a simple ingress-per-app requirer."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v2/ingress.py",
        LIB_ROOT / "traefik_k8s" / "v2" / "ingress.py",
    ))
    files.update(_read_src_files("ipa", ["any_charm.py"]))
    return json.dumps(files)


def ipu_src_overwrite() -> str:
    """Generate src-overwrite config for a simple ingress-per-unit requirer."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v1/ingress_per_unit.py",
        LIB_ROOT / "traefik_k8s" / "v1" / "ingress_per_unit.py",
    ))
    files.update(_read_src_files("ipu", ["any_charm.py"]))
    return json.dumps(files)


def tcp_ipu_src_overwrite() -> str:
    """Generate src-overwrite config for a TCP ingress-per-unit requirer."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v1/ingress_per_unit.py",
        LIB_ROOT / "traefik_k8s" / "v1" / "ingress_per_unit.py",
    ))
    files.update(_read_src_files("tcp_ipu", ["any_charm.py"]))
    return json.dumps(files)


def route_src_overwrite() -> str:
    """Generate src-overwrite config for a traefik-route requirer with UDP echo server."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v0/traefik_route.py",
        LIB_ROOT / "traefik_k8s" / "v0" / "traefik_route.py",
    ))
    files.update(_read_src_files("route", ["any_charm.py", "udp_echo_server.py"]))
    return json.dumps(files)


def forward_auth_src_overwrite() -> str:
    """Generate src-overwrite config for the IAP requirer (forward-auth tester)."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v2/ingress.py",
        LIB_ROOT / "traefik_k8s" / "v2" / "ingress.py",
    ))
    files.update(_lib_files(
        "charms/oathkeeper/v0/auth_proxy.py",
        _OATHKEEPER_LIB,
    ))
    files.update(_read_src_files("forward_auth", ["any_charm.py", "httpbin_server.py"]))
    return json.dumps(files)


def health_src_overwrite() -> str:
    """Generate src-overwrite config for the health tester."""
    files = OrderedDict()
    files.update(_lib_files(
        "charms/traefik_k8s/v2/ingress.py",
        LIB_ROOT / "traefik_k8s" / "v2" / "ingress.py",
    ))
    files.update(_read_src_files("health", ["any_charm.py", "health_server.py"]))
    return json.dumps(files)

