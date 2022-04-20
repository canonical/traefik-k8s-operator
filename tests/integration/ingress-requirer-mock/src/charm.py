#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm the service."""

import logging

from charms.traefik_k8s.v0.ingress import IngressPerAppRequirer
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, Model, WaitingStatus

logger = logging.getLogger(__name__)


class TraefikMockCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        model: Model = self.model

        # todo: abstract and simplify this once IPA too is SDI-free
        if relations := model.relations.get("ingress-per-unit"):
            self.ipu(relations)
        elif relations := model.relations.get("ingress-per-app"):
            self.ipa(relations)
        else:
            self.unit.status = BlockedStatus("not related yet via ipa or ipu")

    def ipu(self, relations):
        relation = relations[0]
        ipu_ingress = IngressPerUnitRequirer(charm=self)

        ipu_ingress.provide_ingress_requirements(host="0.0.0.0", port=80)
        self.unit.status = WaitingStatus("ipu not ready yet")

        try:
            if ipu_ingress.is_ready(relation):
                self.unit.status = ActiveStatus("ipu all good!")
        except Exception as e:
            print("IPU error:", e)

    def ipa(self, relations):
        relation = relations[0]
        ipa_ingress = IngressPerAppRequirer(charm=self, endpoint="ingress-per-app")
        try:
            ipa_ingress.request(host="0.0.0.0", port=80)
            # can raise UnversionedRelation error if we're in a departed hook
        except Exception as e:
            print(f"error requesting ingress: {e}")

        self.unit.status = WaitingStatus("ipa not ready yet")
        try:
            if ipa_ingress.is_ready(relation):
                self.unit.status = ActiveStatus("ipa all good!")
        except Exception as e:
            print("IPA error:", e)


if __name__ == "__main__":
    main(TraefikMockCharm)
