# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a simple ingress-per-app requirer."""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from any_charm_base import AnyCharmBase  # noqa: E402
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer  # noqa: E402


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipa = IngressPerAppRequirer(
            self, host="foo.bar", port=80, relation_name="require-ingress"
        )

    def get_relation_data(self):
        rel = self.ipa.relation
        if rel is None:
            return {"url": None, "app_data": {}, "unit_data": {}}

        def _decode(d):
            result = {}
            for k, v in d.items():
                try:
                    result[k] = json.loads(v)
                except (json.JSONDecodeError, TypeError):
                    result[k] = v
            return result

        return {
            "url": self.ipa.url,
            "app_data": _decode(dict(rel.data[self.app])),
            "unit_data": _decode(dict(rel.data[self.unit])),
        }
