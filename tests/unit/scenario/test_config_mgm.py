from scenario import Relation, State


def ipu():
    return Relation(
        endpoint="ingress-per-unit",
        interface="ingress_per_unit",
        remote_app_name="remote",
        relation_id=0,
        remote_units_data={
            0: {
                "port": "9999",
                "host": '"host"',
                "model": '"test-model"',
                "name": '"remote/0"',
            }
        },
    )


def test_dynamic_config_create(traefik_container, traefik_ctx, tmp_path):
    rel = ipu()
    traefik_ctx.run(
        rel.created_event, State(relations=[rel], containers=[traefik_container], leader=True)
    )
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    assert dynamic_config_dir.exists()
    files = list(dynamic_config_dir.iterdir())
    assert len(files) == 1
    assert files[0].name == f"juju_ingress_ingress-per-unit_{rel.relation_id}_remote.yaml"


def test_dynamic_config_remove_on_broken(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu()
    dynamic_config_dir.mkdir(parents=True)
    ingress_config_fname = (
        dynamic_config_dir / f"juju_ingress_ingress-per-unit_{rel.relation_id}_remote.yaml"
    )
    ingress_config_fname.touch()

    traefik_ctx.run(
        rel.broken_event, State(relations=[rel], containers=[traefik_container], leader=True)
    )

    assert dynamic_config_dir.exists()
    files = list(dynamic_config_dir.iterdir())
    assert len(files) == 0


def test_dynamic_config_remove_on_departed(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu().replace(remote_units_data={})

    dynamic_config_dir.mkdir(parents=True)
    ingress_config_fname = (
        dynamic_config_dir / f"juju_ingress_ingress-per-unit_{rel.relation_id}_remote.yaml"
    )
    ingress_config_fname.touch()

    traefik_ctx.run(
        rel.departed_event(remote_unit_id=0),
        State(relations=[rel], containers=[traefik_container], leader=True),
    )

    assert dynamic_config_dir.exists()
    files = list(dynamic_config_dir.iterdir())
    assert len(files) == 0
