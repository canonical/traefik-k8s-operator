#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase, PebbleReadyEvent
from ops.model import ActiveStatus, Container, WaitingStatus
from ops.pebble import Layer


class TCPRequirerMock(CharmBase):
    _tcp_port = 9999

    def __init__(self, framework):
        """Initialize the mock charm."""
        super().__init__(framework)

        self.unit.open_port("tcp", self._tcp_port)
        self.unit.status = ActiveStatus("ready")

        # dummy charm: only create the relation AFTER pebble ready has fired.

        self.framework.observe(self.on.ingress_per_unit_relation_created, self._ipu_created)
        self.framework.observe(self.on.tcp_server_pebble_ready, self._pebble_ready)

    def _pebble_ready(self, event: PebbleReadyEvent):
        container: Container = event.workload
        if not container.can_connect():
            event.defer()
            self.unit.status = WaitingStatus(
                "Pending webserver restart; waiting for workload container"
            )
            return

        workload_file = Path(__file__).parent / "workload.py"
        with open(workload_file, "r") as workload_source:
            print("pushing webserver source...")
            container.push("/workload.py", workload_source)

        new_layer = Layer(
            {
                "summary": "webserver layer",
                "description": "pebble config layer for workload",
                "services": {
                    "workload": {
                        "override": "replace",
                        "summary": "workload",
                        "command": "python workload.py",
                        "startup": "enabled",
                    }
                },
            }
        )
        container.add_layer("webserver", new_layer, combine=True)
        print("Added updated layer 'webserver' to Pebble plan")

        container.replan()
        print("restarted webserver service")
        self.unit.status = ActiveStatus()

    def _ipu_created(self, _event):
        ipu = IngressPerUnitRequirer(self, mode="tcp")
        ipu.provide_ingress_requirements(port=self._tcp_port)


if __name__ == "__main__":
    from ops.main import main

    main(TCPRequirerMock)
