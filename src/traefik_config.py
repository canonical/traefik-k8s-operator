
#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Traefik config interface."""
from typing import List, TYPE_CHECKING

if TYPE_CHECKING:
    from traefik import Traefik


class _TraefikIngressConfig:
    """Represents an ingress configuration for a single remote entity (app or unit)."""

    def __init__(self, *, unit_name: str, model_name: str, remote_app_name: str, relation_id: int, relation_name: str):
        self._unit_name = unit_name
        self._model_name = model_name
        self._remote_app_name = remote_app_name
        self._relation_id = relation_id
        self._relation_name = relation_name

    @property
    def prefix(self):
        """Prefix of this ingress route."""
        name = self._unit_name.replace("/", "-")
        return f"{self._model_name}-{name}"

    @property
    def filename(self):
        """Filename that this config will be rendered to."""
        # Using both the relation id and the app name in the file to facilitate
        # the debugging experience somewhat when snooping into the container at runtime:
        # Apps not in the same model as Traefik (i.e., if `relation` is a CRM) will have
        # some `remote_...` as app name. Relation name and id are handy when one is
        # troubleshooting via `juju run 'relation_ids'...` and the like.`
        return f"juju_ingress_{self._relation_name}_{self._relation_id}_{self._remote_app_name}.yaml"

    def render(self) -> str:
        raise NotImplementedError


class _TraefikIngressPerUnitConfig(_TraefikIngressConfig):
    pass


class TraefikDynamicConfig:
    def __init__(self, traefik: "Traefik", model_name: str, unit_name: str):
        self._configs: List[_TraefikIngressConfig] = []
        self._traefik = traefik
        self._model_name = model_name
        self._unit_name = unit_name

    def add_ingress_per_unit(self, remote_app_name: str, relation_id: int, relation_name: str):
        self._configs.append(
            _TraefikIngressPerUnitConfig(
                model_name=self._model_name, unit_name=self._unit_name,
                remote_app_name=remote_app_name,
                relation_id=relation_id,
                relation_name=relation_name,
            )
        )

    def push(self):
        for ingress_config in self._configs:
            self._traefik.add_dynamic_config(ingress_config.filename, ingress_config.render())
