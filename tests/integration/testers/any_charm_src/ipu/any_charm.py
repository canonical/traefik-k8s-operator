# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a simple ingress-per-unit requirer."""

import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(__file__))

from any_charm_base import AnyCharmBase  # noqa: E402
from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer  # noqa: E402


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitRequirer(
            self, host="foo.bar", port=80, relation_name="require-ingress-per-unit"
        )

    def get_ingress_data(self):
        """Return ingress URL info for this unit. Callable via rpc action."""
        return {"url": self.ipu.url, "urls": self.ipu.urls or {}}

    def get_relation_data(self):
        """Return the raw relation databag contents. Callable via rpc action.

        This bypasses the traefik_k8s library's own parsing so that callers can
        assert on the actual wire-format/interface contract, not just what the
        library itself is able to read back.
        """
        rel = self.ipu.relation
        if rel is None:
            return {"unit_data": {}, "app_data": {}}

        def _decode(d):
            result = {}
            for k, v in d.items():
                try:
                    result[k] = yaml.safe_load(v)
                except yaml.YAMLError:
                    result[k] = v
            return result

        return {
            "unit_data": _decode(dict(rel.data[self.unit])),
            "app_data": _decode(dict(rel.data[rel.app])),
        }
