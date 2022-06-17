# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from ops.charm import CharmBase

from charms.traefik_k8s.v1.ingress import IngressPerAppRequirer


class IPARequirerMock(CharmBase):
    def __init__(self, framework):
        super().__init__(framework, None)
        self.ipa = IngressPerAppRequirer(self, host='foo.bar', port=80)


if __name__ == '__main__':
    from ops.main import main

    main(IPARequirerMock)
