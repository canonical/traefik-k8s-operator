#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the service."""

import logging

from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Model, WaitingStatus

logger = logging.getLogger(__name__)


class TraefikMockCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        ingress = IngressPerUnitRequirer(charm=self)
        model: Model = self.model
        ipu_relations = model.relations.get("ingress-per-unit")

        if ipu_relations:
            ipu_relation = ipu_relations[0]
            ingress.provide_ingress_requirements(host="0.0.0.0", port=80)

            if ingress.is_ready(ipu_relation):
                self.unit.status = ActiveStatus("all good!")
            else:
                self.unit.status = WaitingStatus("ipu not ready yet")
        else:
            self.unit.status = BlockedStatus("ipu not related")


if __name__ == "__main__":
    main(TraefikMockCharm)
