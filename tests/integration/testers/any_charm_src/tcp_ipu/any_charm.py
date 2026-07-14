# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for a TCP ingress-per-unit requirer.

Runs a TCP echo server via pebble and provides ingress requirements in TCP mode.
"""

import pathlib
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.pebble import Layer

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer  # noqa: E402

_TCP_PORT = 9999


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressPerUnitRequirer(
            self,
            mode="tcp",
            port=_TCP_PORT,
            relation_name="require-ingress-per-unit",
        )
        self.unit.open_port("tcp", _TCP_PORT)
        self.framework.observe(self.on["any"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(
            self.on["require-ingress-per-unit"].relation_created, self._ipu_created
        )
        self.unit.status = ops.ActiveStatus("ready")

    def _on_pebble_ready(self, event):
        container = event.workload
        container.exec(["apt-get", "update", "-qq"]).wait()
        container.exec(["apt-get", "install", "-y", "-qq", "python3"]).wait()
        server_script = (_src / "tcp_echo_server.py").read_text()
        container.push("/tcp_echo_server.py", server_script, make_dirs=True)
        layer = Layer({
            "summary": "tcp-echo layer",
            "services": {
                "tcp-echo": {
                    "override": "replace",
                    "command": "python3 /tcp_echo_server.py",
                    "startup": "enabled",
                }
            },
        })
        container.add_layer("tcp-echo", layer, combine=True)
        container.replan()
        self._ipu_created(None)
        self.unit.status = ops.ActiveStatus("ready")

    def _ipu_created(self, _event):
        self.ipu.provide_ingress_requirements(port=_TCP_PORT)

    def get_tcp_ingress_data(self):
        """Return ingress URL info for this unit. Callable via rpc action."""
        return {"url": self.ipu.url, "urls": self.ipu.urls or {}}
