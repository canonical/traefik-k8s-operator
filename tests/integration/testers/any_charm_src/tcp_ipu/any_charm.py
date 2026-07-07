# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a TCP ingress-per-unit requirer."""

import os
import pathlib
import sys

_src = pathlib.Path(os.path.dirname(__file__))
_lib_dir = _src / "charms" / "traefik_k8s" / "v1"
_lib_dir.mkdir(parents=True, exist_ok=True)
(_src / "charms" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "v1" / "__init__.py").touch(exist_ok=True)
_lib_src = _src / "_lib_ingress_per_unit_v1.py"
_lib_dst = _lib_dir / "ingress_per_unit.py"
if _lib_src.exists() and not _lib_dst.exists():
    _lib_dst.write_text(_lib_src.read_text())

sys.path.insert(0, str(_src))

from any_charm_base import AnyCharmBase  # noqa: E402
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer  # noqa: E402


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.framework.observe(
            self.on["require-ingress-per-unit"].relation_created, self._ipu_created
        )

    def _ipu_created(self, _event):
        ipu = IngressPerUnitRequirer(
            self, mode="tcp", relation_name="require-ingress-per-unit"
        )
        ipu.provide_ingress_requirements(port=9999)
