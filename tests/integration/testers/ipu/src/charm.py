#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from ops.model import ActiveStatus

from charms.traefik_k8s.v1.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase


class IPURequirerMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework, None)
        self.ipu = IngressPerUnitRequirer(self, host="foo.bar", port=80)
        self.unit.status = ActiveStatus("ready")


if __name__ == "__main__":
    from ops.main import main

    main(IPURequirerMock)
