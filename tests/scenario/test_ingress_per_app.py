# GIVEN a charm with ingress impl'd
# WHEN a relation with traefik is formed
# THEN traefik's config file's `server` section has all the units listed
# AND WHEN the charm rescales
# THEN the traefik config file is updated


import pytest
import yaml
from ops import pebble
from scenario import Container, Model, Mount, Relation, State


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
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_ingress_per_app_created(
        traefik_ctx, port, host, model, traefik_container, event_name, tmp_path, scheme
):
    """Check the config when a new ingress per app is created or changes (single remote unit)."""
    ipa = Relation(
        "ingress",
        remote_app_data={
            "model": "test-model",
            "name": "remote/0",
            "mode": "http",
            "port": str(port),
            "scheme": scheme,
        },
        remote_units_data={0: {"port": str(port), "host": host}},
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

    service_def = {
        "loadBalancer": {"servers": [{"url": f"{scheme}://{host}:{port}"}]},
    }
    # no tls relation = no rootCAs section
    # if scheme == 'https':
    #     service_def["rootCAs"] = ["/opt/traefik/juju/certificate.cert"]

    assert generated_config["http"]["services"]["juju-test-model-remote-0-service"] == service_def


@pytest.mark.parametrize("port, host", ((80, "1.1.1.{}"), (81, "10.1.10.{}")))
@pytest.mark.parametrize("n_units", (2, 3, 10))
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_ingress_per_app_scale(
        traefik_ctx, host, port, model, traefik_container, tmp_path, n_units, scheme
):
    """Check the config when a new ingress per app unit joins."""
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
            "scheme": scheme,
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

    traefik_ctx.run(ipa.changed_event, state)

    new_config = yaml.safe_load(cfg_file.read_text())
    # verify that the config has changed!
    new_lbs = new_config["http"]["services"]["juju-test-model-remote-service"]["loadBalancer"][
        "servers"
    ]

    assert len(new_lbs) == n_units
    for n in range(n_units):
        assert {"url": f"{scheme}://{host.format(n)}:{port}"} in new_lbs

        # expected config:

        # IPA:
        # len(d["service"][svc_name]["loadBalancer"]["servers"]) == num_units
        # [x["url"] for x in d["service"][svc_name]["loadBalancer"]["servers"]] == all_units_urls

        # IPL:
        # len(d["service"][svc_name]["loadBalancer"]["servers"]) == 1
        # d["service"][svc_name]["loadBalancer"]["servers"][0]["url"] == leader_url
