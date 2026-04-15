import yaml
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
    merged_file = dynamic_config_dir / "juju_ingress.yaml"
    assert merged_file.exists()
    # Merged file should contain valid traefik config
    merged_config = yaml.safe_load(merged_file.read_text())
    assert "http" in merged_config or "tcp" in merged_config


def test_dynamic_config_remove_on_broken(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu()
    dynamic_config_dir.mkdir(parents=True)

    # Pre-create the merged file with this relation's config.
    dummy_config = {"http": {"routers": {"r": {"rule": "Host(`test`)"}}}}
    (dynamic_config_dir / "juju_ingress.yaml").write_text(yaml.safe_dump(dummy_config))

    traefik_ctx.run(
        rel.broken_event, State(relations=[rel], containers=[traefik_container], leader=True)
    )

    assert dynamic_config_dir.exists()
    # No remaining relations, so merged file should be gone.
    assert not (dynamic_config_dir / "juju_ingress.yaml").exists()


def test_dynamic_config_remove_on_departed(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu().replace(remote_units_data={})

    dynamic_config_dir.mkdir(parents=True)

    # Pre-create the merged file with this relation's config.
    dummy_config = {"http": {"routers": {"r": {"rule": "Host(`test`)"}}}}
    (dynamic_config_dir / "juju_ingress.yaml").write_text(yaml.safe_dump(dummy_config))

    traefik_ctx.run(
        rel.departed_event(remote_unit_id=0),
        State(relations=[rel], containers=[traefik_container], leader=True),
    )

    assert dynamic_config_dir.exists()
    # No remaining relations, so merged file should be gone.
    assert not (dynamic_config_dir / "juju_ingress.yaml").exists()
