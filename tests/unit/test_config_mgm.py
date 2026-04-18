import yaml
from scenario import Relation, State

from traefik import INGRESS_CONFIG_PREFIX


def _find_ingress_configs(config_dir):
    """Return list of per-relation ingress config files in *config_dir*."""
    return [
        p
        for p in config_dir.iterdir()
        if p.name.startswith(INGRESS_CONFIG_PREFIX) and p.name.endswith(".yaml")
    ]


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
    ingress_files = _find_ingress_configs(dynamic_config_dir)
    assert ingress_files, "Expected at least one per-relation ingress config file"
    # Each file should contain valid traefik config
    for f in ingress_files:
        config = yaml.safe_load(f.read_text())
        assert "http" in config or "tcp" in config


def test_dynamic_config_remove_on_broken(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu()
    dynamic_config_dir.mkdir(parents=True)

    # Pre-create a per-relation config file.
    sample_config = {"http": {"routers": {"r": {"rule": "Host(`test`)"}}}}
    (dynamic_config_dir / "juju_ingress_ingress-per-unit_0_remote.yaml").write_text(
        yaml.safe_dump(sample_config)
    )

    traefik_ctx.run(
        rel.broken_event, State(relations=[rel], containers=[traefik_container], leader=True)
    )

    assert dynamic_config_dir.exists()
    # No remaining relations, so per-relation config files should be gone.
    assert not _find_ingress_configs(dynamic_config_dir)


def test_dynamic_config_remove_on_departed(traefik_container, traefik_ctx, tmp_path):
    dynamic_config_dir = tmp_path / "traefik" / "juju"
    rel = ipu().replace(remote_units_data={})

    dynamic_config_dir.mkdir(parents=True)

    # Pre-create a per-relation config file.
    sample_config = {"http": {"routers": {"r": {"rule": "Host(`test`)"}}}}
    (dynamic_config_dir / "juju_ingress_ingress-per-unit_0_remote.yaml").write_text(
        yaml.safe_dump(sample_config)
    )

    traefik_ctx.run(
        rel.departed_event(remote_unit_id=0),
        State(relations=[rel], containers=[traefik_container], leader=True),
    )

    assert dynamic_config_dir.exists()
    # No remaining relations, so per-relation config files should be gone.
    assert not _find_ingress_configs(dynamic_config_dir)
