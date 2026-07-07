# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a TCP ingress-per-unit requirer."""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

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
