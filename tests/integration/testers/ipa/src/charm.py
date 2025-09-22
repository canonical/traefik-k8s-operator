#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops.charm import CharmBase
from ops.model import ActiveStatus


class IPARequirerMock(CharmBase):
    def __init__(self, framework):
        """Initialize the mock charm."""
        super().__init__(framework)
        self.ipa = IngressPerAppRequirer(self, host="foo.bar", port=80)
        self.unit.status = ActiveStatus("ready")


if __name__ == "__main__":
    from ops.main import main

    main(IPARequirerMock)
