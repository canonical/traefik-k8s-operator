from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

import yaml
from scenario import Context, Relation, State
from scenario.context import CharmEvents
from scenario.state import _DEFAULT_JUJU_DATABAG

on = CharmEvents()


def create(traefik_ctx: Context, state: State):
    """Create the ingress relation."""
    ingress = Relation("ingress")
    return traefik_ctx.run(on.relation_joined(ingress), replace(state, relations=[ingress]))


def join(traefik_ctx: Context, state: State):
    """Simulate a new unit joining the ingress relation."""
    ingress = state.get_relations("ingress")[0]
    state = traefik_ctx.run(on.relation_joined(ingress), state)
    remote_units_data = ingress.remote_units_data

    joining_unit_id = max(remote_units_data)
    if set(remote_units_data[joining_unit_id]).difference(_DEFAULT_JUJU_DATABAG):
        joining_unit_id += 1

    remote_units_data[joining_unit_id] = {
        "host": f'"neutron-{joining_unit_id}.neutron-endpoints.zaza-de71889d82db.svc.cluster.local"'
    }
    relations = [
        replace(
            ingress,
            remote_app_data={
                "model": '"zaza"',
                "name": '"neutron"',
                "port": "9696",
                "redirect-https": "false",
                "scheme": '"http"',
                "strip-prefix": "false",
            },
            remote_units_data=remote_units_data,
        )
    ]

    state_with_remotes = replace(state, relations=relations)
    state = traefik_ctx.run(
        on.relation_changed(state_with_remotes.get_relations("ingress")[0]), state_with_remotes
    )
    return state


def depart(traefik_ctx: Context, state: State):
    """Simulate a unit departing the ingress relation."""

    def _pop(state: State):
        ingress = state.get_relations("ingress")[0]
        remote_units_data = ingress.remote_units_data.copy()
        departing_unit_id = max(remote_units_data)
        del remote_units_data[departing_unit_id]
        return replace(state, relations=[replace(ingress, remote_units_data=remote_units_data)])

    state = _pop(state)

    state = traefik_ctx.run(on.relation_departed(state.get_relations("ingress")[0]), state)
    return state


def break_(traefik_ctx: Context, state: State):
    """Simulate breaking the ingress relation."""
    for _ in state.get_relations("ingress")[0].remote_units_data:
        # depart all units
        depart(traefik_ctx, state)

    ingress = state.get_relations("ingress")[0]
    cleared_remote_ingress = replace(ingress, remote_app_data={}, remote_units_data={})
    return traefik_ctx.run(
        on.relation_broken(cleared_remote_ingress),
        replace(state, relations=[cleared_remote_ingress]),
    )


def get_configs(traefik_ctx: Context, state: State) -> Tuple[Path, List[Path]]:
    """Return static and dynamic configs."""
    vfs_root = state.get_container("traefik").get_filesystem(traefik_ctx)
    opt = vfs_root / "opt" / "traefik" / "juju"
    etc = vfs_root / "etc" / "traefik" / "traefik.yaml"
    return etc, list(opt.glob("*.yaml"))


def get_servers(cfg: Path):
    """Return a list of servers from the traefik config."""
    cfg_yaml = yaml.safe_load(cfg.read_text())
    return cfg_yaml["http"]["services"]["juju-zaza-neutron-service"]["loadBalancer"]["servers"]


def test_traefik_remote_app_scaledown_from_2(traefik_ctx, traefik_container):
    """Verify that on scale up and down traefik always has the right amount of servers configured.

    TODO: parametrize
    """
    state = State(containers=[traefik_container])

    with traefik_ctx(on.pebble_ready(traefik_container), state) as mgr:
        state = mgr.run()
        static, dynamic = get_configs(traefik_ctx, state)

    assert static.exists()
    assert len(dynamic) == 0

    state = create(traefik_ctx, state)

    state = join(traefik_ctx, state)

    _, dynamic = get_configs(traefik_ctx, state)
    assert len(dynamic) == 1
    assert len(get_servers(dynamic[0])) == 1

    state = join(traefik_ctx, state)

    _, dynamic = get_configs(traefik_ctx, state)
    assert len(get_servers(dynamic[0])) == 2

    state = depart(traefik_ctx, state)

    _, dynamic = get_configs(traefik_ctx, state)
    assert len(get_servers(dynamic[0])) == 1

    break_(traefik_ctx, state)
    assert not dynamic[0].exists()
