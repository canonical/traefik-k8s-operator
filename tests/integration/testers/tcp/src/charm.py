#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path
from socket import getfqdn

from ops.pebble import Layer

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase, PebbleReadyEvent
from ops.model import ActiveStatus, Container, WaitingStatus


class TCPRequirerMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework, None)
        self.ipa = IngressPerUnitRequirer(self, host="foo.bar", port=80)
        self.unit.status = ActiveStatus("ready")

        self.framework.observe(self.ipa.on.ready_for_unit, self._ipu_ready)
        self.framework.observe(self.on.tcp_server_pebble_ready, self._pebble_ready)

    def _pebble_ready(self, event: PebbleReadyEvent):
        container: Container = event.workload
        if container.can_connect():
            # ensure the container is set up
            container.exec('pip install fastapi uvicorn'.split())
            workload_file = Path(__file__).parent / 'workload.py'
            with open(workload_file, 'r') as workload_source:
                print('pushing webserver source...')
                container.push('/workload.py', workload_source)

            new_layer = Layer({
                "summary": "webserver layer",
                "description": "pebble config layer for workload",
                "services": {
                    "workload": {
                        "override": "replace",
                        "summary": "workload",
                        "command": "python workload.py",
                        "startup": "enabled"
                    }}})

            # Check if there are any changes to layer services.
            if container.get_plan().services != new_layer.services:
                # Changes were made, add the new layer.
                container.add_layer('webserver', new_layer, combine=True)
                print("Added updated layer 'webserver' to Pebble plan")
                # Restart it and report a new status to Juju.
                container.replan()
                print("restarted webserver service")

            self.unit.status = ActiveStatus()
        else:
            self.unit.status = WaitingStatus(
                'Pending webserver restart; waiting for workload container'
            )

    def _ipu_ready(self, event):
        # patch databag by adding some extra data
        event.relation.data[self.unit]['tcp-port'] = '42'
        event.relation.data[self.unit]['tcp-ip'] = getfqdn()


if __name__ == "__main__":
    from ops.main import main

    main(TCPRequirerMock)
