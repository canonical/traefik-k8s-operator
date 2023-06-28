#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""Endpoint deprecator lib."""
import logging

from ops import CharmBase, Relation, UnknownStatus, WaitingStatus, ActiveStatus, StatusBase

logger = logging.getLogger(__name__)


class UnsupportedInterface(RuntimeError):
    """Raised if a relation interface can't be remapped."""


def _is_empty(relation: Relation):
    return not _is_nonempty(relation)


def _is_nonempty(relation: Relation):
    return relation.data[relation.app] or any((relation.data[unit] for unit in relation.units))


def _compute_remapping(relation: Relation, remappings):
    for (version, wrapper, accept), event_remap in remappings:
        if accept(relation):
            logger.info(f"{relation} accepted by {wrapper} @version {version!r}")
            return event_remap
        logger.warning(f'{relation} could not accept preferred version {version}: falling back down')
    raise UnsupportedInterface(f"relation {relation} not accepted by any supported wrapper")


class EventRemapper:
    def __init__(self, charm: CharmBase, endpoint: str, remappings):
        self._charm = charm
        self._endpoint = endpoint
        self._remappings = remappings

        self._status = UnknownStatus()

        # setup observers
        relations = self._charm.model.relations[self._endpoint]
        nonempty_relations = tuple(filter(_is_nonempty, relations))

        if not nonempty_relations:
            logger.info("all relations are empty... setting waiting status")
            self._status = WaitingStatus("waiting on relation data")
        else:
            remapping, rejected = {}, []

            for relation in nonempty_relations:
                try:
                    remapping.update(_compute_remapping(relation, self._remappings))
                except UnsupportedInterface:
                    logger.error(f"Error attempting to remap {relation}", exc_info=True)
                    rejected.append(relation)
                    continue

            some_empty_relations = tuple(filter(_is_empty, relations))

            error_msg = ""
            if rejected:
                error_msg = f"Some relations on {endpoint} were rejected and are unsupported"

            if some_empty_relations:
                error_msg += f"Some relations on {endpoint} are still empty."

            if error_msg:
                # active but degraded
                logger.error(error_msg)
                self._status = ActiveStatus("degraded (see logs)")
            else:
                self._status = ActiveStatus()

            for event, observer in remapping.items():
                self._charm.framework.observe(event, observer)

    @property
    def status(self) -> StatusBase:
        return self._status
