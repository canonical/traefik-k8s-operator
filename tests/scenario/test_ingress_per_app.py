# GIVEN a charm with ingress impl'd
# WHEN a relation with traefik is formed
# THEN traefik's config file's `server` section has all the units listed
# AND WHEN the charm rescales
# THEN the traefik config file is updated


import pytest
import yaml
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer
from ops import CharmBase, Framework, pebble
from scenario import Container, Context, Model, Mount, Relation, State


@pytest.fixture
def model():
    return Model(name="test-model")


@pytest.fixture
def traefik_container(tmp_path):
    layer = pebble.Layer(
        {
            "summary": "Traefik layer",
            "description": "Pebble config layer for Traefik",
            "services": {
                "traefik": {
                    "override": "replace",
                    "summary": "Traefik",
                    "command": '/bin/sh -c "/usr/bin/traefik | tee /var/log/traefik.log"',
                    "startup": "enabled",
                },
            },
        }
    )

    opt = Mount("/opt/", tmp_path)

    return Container(
        name="traefik",
        can_connect=True,
        layers={"traefik": layer},
        service_status={"traefik": pebble.ServiceStatus.ACTIVE},
        mounts={"opt": opt},
    )


@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
@pytest.mark.parametrize("event_name", ("joined", "changed", "created"))
def test_ingress_per_app_created(
    traefik_ctx, port, host, model, traefik_container, event_name, tmp_path
):
    """Check the config when a new ingress per leader is created or changes (single remote unit)."""
    ipa = Relation(
        "ingress",
        remote_app_data={
            "model": "test-model",
            "name": "remote/0",
            "port": str(port),
            "mode": "http",
        },
        remote_units_data={0: {"host": host}},
        relation_id=1,
    )
    state = State(
        model=model,
        config={"routing_mode": "path", "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipa],
    )

    # WHEN any relevant event fires
    event = getattr(ipa, f"{event_name}_event")
    traefik_ctx.run(event, state)

    generated_config = yaml.safe_load(
        traefik_container.filesystem.open(
            f"/opt/traefik/juju/juju_ingress_ingress_{ipa.relation_id}_remote.yaml"
        ).read()
    )

    assert generated_config["http"]["services"]["juju-test-model-remote-0-service"] == {
        "loadBalancer": {"servers": [{"url": f"http://{host}:{port}"}]}
    }


@pytest.mark.parametrize("port, host", ((80, "1.1.1.{}"), (81, "10.1.10.{}")))
@pytest.mark.parametrize("n_units", (2, 3, 10))
@pytest.mark.parametrize("evt_name", ("joined", "changed"))
def test_ingress_per_app_scale(
    traefik_ctx, host, port, model, traefik_container, tmp_path, n_units, evt_name
):
    """Check the config when a new ingress per leader unit joins."""
    cfg_file = tmp_path.joinpath("traefik", "juju", "juju_ingress_ingress_1_remote.yaml")
    cfg_file.parent.mkdir(parents=True)

    # config that would have been generated from mock_data_0
    # same as config output of the previous test
    initial_cfg = {
        "http": {
            "routers": {
                "juju-test-model-remote-0-router": {
                    "entryPoints": ["web"],
                    "rule": "PathPrefix(`/test-model-remote-0`)",
                    "service": "juju-test-model-remote-0-service",
                },
                "juju-test-model-remote-0-router-tls": {
                    "entryPoints": ["websecure"],
                    "rule": "PathPrefix(`/test-model-remote-0`)",
                    "service": "juju-test-model-remote-0-service",
                    "tls": {"domains": [{"main": "foo.com", "sans": ["*.foo.com"]}]},
                },
            },
            "services": {
                "juju-test-model-remote-0-service": {
                    "loadBalancer": {"servers": [{"url": f"http://{host}:{port}"}]}
                }
            },
        }
    }
    cfg_file.write_text(yaml.safe_dump(initial_cfg))

    def _get_mock_data(n: int):
        return {
            "host": host.format(n),
        }

    ipa = Relation(
        "ingress",
        remote_app_data={
            "model": "test-model",
            "name": "remote",
            "port": str(port),
        },
        remote_units_data={n: _get_mock_data(n) for n in range(n_units)},
        relation_id=1,
    )
    state = State(
        model=model,
        config={"routing_mode": "path", "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipa],
    )

    traefik_ctx.run(getattr(ipa, evt_name + "_event"), state)

    new_config = yaml.safe_load(cfg_file.read_text())
    # verify that the config has changed!
    new_lbs = new_config["http"]["services"]["juju-test-model-remote-service"]["loadBalancer"][
        "servers"
    ]

    assert len(new_lbs) == n_units
    for n in range(n_units):
        assert {"url": f"http://{host.format(n)}:{port}"} in new_lbs

        # expected config:

        # IPA:
        # len(d["service"][svc_name]["loadBalancer"]["servers"]) == num_units
        # [x["url"] for x in d["service"][svc_name]["loadBalancer"]["servers"]] == all_units_urls

        # IPL:
        # len(d["service"][svc_name]["loadBalancer"]["servers"]) == 1
        # d["service"][svc_name]["loadBalancer"]["servers"][0]["url"] == leader_url


@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
@pytest.mark.parametrize("evt_name", ("joined", "changed"))
@pytest.mark.parametrize("leader", (True, False))
def test_ingress_per_app_requirer_with_auto_data(host, port, model, evt_name, leader):
    class MyRequirer(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.ipa = IngressPerAppRequirer(self, host=host, port=port)

    ctx = Context(
        charm_type=MyRequirer,
        meta={"name": "charlie", "requires": {"ingress": {"interface": "ingress"}}},
    )

    ipa = Relation("ingress")
    state = State(
        model=model,
        leader=leader,
        relations=[ipa],
    )

    state_out = ctx.run(getattr(ipa, evt_name + "_event"), state)

    ipa_out = state_out.get_relations("ingress")[0]
    assert ipa_out.local_unit_data == {"host": host}

    if leader:
        assert ipa_out.local_app_data == {
            "model": "test-model",
            "name": "charlie",
            "port": str(port),
        }
