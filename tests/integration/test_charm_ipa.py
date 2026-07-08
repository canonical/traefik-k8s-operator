#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for ingress-per-app (IPA) using jubilant."""

import json
import textwrap
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import jubilant
import yaml

from tests.integration.helpers import (
    all_settled,
    assert_can_connect,
    get_k8s_service_address,
    remove_application,
)

TRAEFIK_APP = "traefik-k8s"
IPA_TESTER_APP = "ipa-tester"

_METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
_TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in _METADATA["resources"].items()
}

# any-charm injects this code into its src/ at deploy time, replicating the
# legacy ipa-tester charm: request ingress with known host/port and expose
# all relation data in a single RPC call.
#
# We intentionally implement the v2 ingress protocol directly (rather than
# importing our library) to avoid the pydantic dependency inside any-charm:
#   - host in unit databag (json-encoded)
#   - model + name + port in app databag (json-encoded)
#   - provider writes back the URL via the "ingress" key in its app databag
_ANY_CHARM_SRC_OVERWRITE = {
    "any_charm.py": textwrap.dedent(
        """\
        import json
        from ops import Application
        from any_charm_base import AnyCharmBase

        _HOST = "foo.bar"
        _PORT = 80

        class AnyCharm(AnyCharmBase):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                self.framework.observe(
                    self.on.require_ingress_relation_joined, self._on_ingress_joined
                )

            def _on_ingress_joined(self, event):
                # v2 protocol: each value is json-encoded; model+name+port in
                # app databag, host in unit databag
                event.relation.data[self.app].update({
                    "model": json.dumps(self.model.name),
                    "name": json.dumps(self.app.name),
                    "port": json.dumps(_PORT),
                })
                event.relation.data[self.unit]["host"] = json.dumps(_HOST)

            def get_relation_data(self):
                rel = self.model.get_relation("require-ingress")
                if rel is None:
                    return {"url": None, "app_data": {}, "unit_data": {}}
                url = None
                for bucket in rel.data:
                    if isinstance(bucket, Application) and bucket.name != self.app.name:
                        raw = rel.data[bucket].get("ingress")
                        if raw:
                            url = json.loads(raw).get("url")
                        break

                def _decode(d):
                    result = {}
                    for k, v in d.items():
                        try:
                            result[k] = json.loads(v)
                        except (json.JSONDecodeError, TypeError):
                            result[k] = v
                    return result

                return {
                    "url": url,
                    "app_data": _decode(dict(rel.data[self.app])),
                    "unit_data": _decode(dict(rel.data[self.unit])),
                }
        """
    ),
}


def test_deployment(juju: jubilant.Juju, traefik_charm):
    juju.deploy(traefik_charm, TRAEFIK_APP, resources=_TRAEFIK_RESOURCES, trust=True)
    juju.deploy(
        "ch:any-charm",
        IPA_TESTER_APP,
        channel="beta",
        config={"src-overwrite": json.dumps(_ANY_CHARM_SRC_OVERWRITE)},
    )
    juju.wait(all_settled, timeout=600)


def test_relate(juju: jubilant.Juju):
    juju.integrate(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(all_settled, timeout=600)


def test_ipa_charm_has_ingress(juju: jubilant.Juju):
    data = _rpc(juju, "get_relation_data")
    url = data["url"]
    assert url, "Expected a non-empty ingress URL"
    parsed = urlparse(url)
    assert_can_connect(parsed.hostname, parsed.port or 80)


def test_relation_data_shape(juju: jubilant.Juju):
    data = _rpc(juju, "get_relation_data")

    # Provider gave back a well-formed URL pointing at the actual LB IP
    traefik_address = get_k8s_service_address(juju.model, f"{TRAEFIK_APP}-lb")
    assert traefik_address, "Expected a traefik load balancer address"
    assert data["url"] == f"http://{traefik_address}/{juju.model}-{IPA_TESTER_APP}"

    # Requirer app databag (v2): model + name + port present; host must NOT be here
    assert data["app_data"].get("model") == juju.model
    assert data["app_data"].get("name") == IPA_TESTER_APP
    assert data["app_data"].get("port") == 80
    assert "host" not in data["app_data"], "v2: host must not be in app databag"

    # Requirer unit databag (v2): host IS here
    assert data["unit_data"].get("host") == "foo.bar"


def test_remove_relation(juju: jubilant.Juju):
    juju.remove_relation(f"{IPA_TESTER_APP}:require-ingress", f"{TRAEFIK_APP}:ingress")
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP, IPA_TESTER_APP)
            and jubilant.all_agents_idle(status)
        ),
        timeout=300,
    )
    data = _rpc(juju, "get_relation_data")
    assert not data["url"], "Expected ingress URL to be cleared after relation removal"


def test_cleanup(juju: jubilant.Juju):
    remove_application(juju, TRAEFIK_APP, timeout=60)


def _rpc(juju: jubilant.Juju, method: str) -> Any:
    raw = juju.run(f"{IPA_TESTER_APP}/0", "rpc", params={"method": method}).results["return"]
    return json.loads(raw)  # rpc action json.dumps the return value
