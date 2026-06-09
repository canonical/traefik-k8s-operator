# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import MagicMock, patch

import pytest
from scenario import State


@pytest.mark.parametrize(
    "planned_units, expect_delete",
    [
        (0, True),
        (2, False),
    ],
    ids=["last_unit_deletes_lb", "remaining_units_skips_deletion"],
)
def test_on_remove_lb_deletion(traefik_ctx, traefik_container, planned_units, expect_delete):
    """The LB should only be deleted when this is the last unit being removed."""
    state = State(
        leader=True,
        containers=[traefik_container],
        planned_units=planned_units,
    )

    mock_klm = MagicMock()
    with patch(
        "charm.TraefikIngressCharm._get_lb_resource_manager", return_value=mock_klm
    ):
        traefik_ctx.run("remove", state)

    if expect_delete:
        mock_klm.delete.assert_called_once()
    else:
        mock_klm.delete.assert_not_called()
