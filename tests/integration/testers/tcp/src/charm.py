#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path
from socket import getfqdn

from ops.pebble import Layer, ProtocolError

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase, PebbleReadyEvent
from ops.model import ActiveStatus, Container, WaitingStatus, Relation


class TCPRequirerMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework, None)
        self.unit.status = ActiveStatus("ready")

        self.framework.observe(self.on.ingress_per_unit_relation_created,
                               self._ipu_ready)
        self.framework.observe(self.on.tcp_server_pebble_ready,
                               self._pebble_ready)

    def _pebble_ready(self, event: PebbleReadyEvent):
        container: Container = event.workload
        if container.can_connect():
            # ensure the container is set up
            # FIXME: this doesn't work for some reason
            container.exec("/usr/local/bin/pip install fastapi 'uvicorn[standard]'".split())
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

            # if we're related when pebble starts, go ahead
            for relation in self.model.relations['ingress-per-unit']:
                self._push_data(relation)

            self.unit.status = ActiveStatus()
        else:
            self.unit.status = WaitingStatus(
                'Pending webserver restart; waiting for workload container'
            )

    @property
    def tcp_port(self):
        container = self.unit.get_container('tcp-server')
        if not container.can_connect():
            print('unable to fetch port; container not ready')
            return None
        try:
            return container.pull('/port.txt').read()
        except ProtocolError as e:
            print('port file not found in container.')
            raise

    def _ipu_ready(self, event):
        self._push_data(event.relation)

    def _push_data(self, relation: Relation):
        tcp_port = self.tcp_port
        if not tcp_port:
            return

        # todo replace with IPURequirer when tcp mode supported
        ipu = {'host': "foo.bar",
               'port': str(tcp_port),
               'model': self.model.name,
               'name': self.unit.name,
               'mode': 'tcp'}

        for k, v in ipu.items():
            relation.data[self.unit][k] = v


if __name__ == "__main__":
    from ops.main import main

    main(TCPRequirerMock)
