# GIVEN a charm with ingress impl'd
# WHEN a relation with traefik is formed
# THEN traefik's config file's `server` section has all the units listed
# AND WHEN the charm rescales
# THEN the traefik config file is updated
import json
import tempfile
from pathlib import Path

import pytest
import yaml
from charms.traefik_k8s.v2.ingress import (
    IngressPerAppRequirer,
    IngressRequirerAppData,
    IngressRequirerUnitData,
)
from ops import CharmBase, Framework
from scenario import Context, Mount, Relation, State

from tests.scenario.utils import create_ingress_relation


@pytest.mark.parametrize(
    "port, ip, host", ((80, "1.1.1.1", "1.1.1.1"), (81, "10.1.10.1", "10.1.10.1"))
)
@pytest.mark.parametrize("event_name", ("joined", "changed", "created"))
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_ingress_per_app_created(
    traefik_ctx, port, ip, host, model, traefik_container, event_name, tmp_path, scheme
):
    """Check the config when a new ingress per app is created or changes (single remote unit)."""
    ipa = create_ingress_relation(port=port, scheme=scheme, hosts=[host], ips=[ip])
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
        traefik_container.get_filesystem(traefik_ctx)
        .joinpath(f"opt/traefik/juju/juju_ingress_ingress_{ipa.relation_id}_remote.yaml")
        .read_text()
    )

    service_def = {
        "loadBalancer": {"servers": [{"url": f"{scheme}://{host}:{port}"}]},
    }

    if scheme == "https":
        # traefik has no tls relation, but the requirer does: reverse termination case
        # service_def["rootCAs"] = ["/opt/traefik/juju/certificate.cert"]
        service_def["loadBalancer"]["serversTransport"] = "reverseTerminationTransport"
        # service_def["serversTransports"] = {
        #     "reverseTerminationTransport": {"insecureSkipVerify": True}
        # }

    assert generated_config["http"]["services"]["juju-test-model-remote-0-service"] == service_def


@pytest.mark.parametrize(
    "port, ip, host", ((80, "1.1.1.{}", "1.1.1.{}"), (81, "10.1.10.{}", "10.1.10.{}"))
)
@pytest.mark.parametrize("n_units", (2, 3, 10))
@pytest.mark.parametrize("evt_name", ("joined", "changed"))
@pytest.mark.parametrize("scheme", ("http", "https"))
def test_ingress_per_app_scale(
    traefik_ctx, host, ip, port, model, traefik_container, tmp_path, n_units, scheme, evt_name
):
    """Check the config when a new ingress per app unit joins."""
    relation_id = 42
    unit_id = 0
    cfg_file = tmp_path.joinpath(
        "traefik", "juju", f"juju_ingress_ingress_{relation_id}_remote.yaml"
    )
    cfg_file.parent.mkdir(parents=True)

    # config that would have been generated from mock_data_0
    # same as config output of the previous test
    initial_cfg = {
        "http": {
            "routers": {
                f"juju-test-model-remote-{unit_id}-router": {
                    "entryPoints": ["web"],
                    "rule": f"PathPrefix(`/test-model-remote-{unit_id}`)",
                    "service": f"juju-test-model-remote-{unit_id}-service",
                },
                f"juju-test-model-remote-{unit_id}-router-tls": {
                    "entryPoints": ["websecure"],
                    "rule": f"PathPrefix(`/test-model-remote-{unit_id}`)",
                    "service": f"juju-test-model-remote-{unit_id}-service",
                    "tls": {"domains": [{"main": "foo.com", "sans": ["*.foo.com"]}]},
                },
            },
            "services": {
                f"juju-test-model-remote-{unit_id}-service": {
                    "loadBalancer": {"servers": [{"url": f"{scheme}://{host.format(0)}:{port}"}]}
                }
            },
        }
    }
    cfg_file.write_text(yaml.safe_dump(initial_cfg))

    ipa = create_ingress_relation(
        port=port,
        scheme=scheme,
        rel_id=relation_id,
        unit_name="remote/0",
        hosts=[host.format(n) for n in range(n_units)],
        ips=[ip.format(n) for n in range(n_units)],
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
    new_lbs = new_config["http"]["services"][f"juju-test-model-remote-{unit_id}-service"][
        "loadBalancer"
    ]["servers"]

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


@pytest.mark.parametrize(
    "port, ip, host", ((80, "1.1.1.1", "1.1.1.1"), (81, "10.1.10.1", "10.1.10.1"))
)
@pytest.mark.parametrize("evt_name", ("joined", "changed"))
@pytest.mark.parametrize("leader", (True, False))
def get_requirer_ctx(host, ip, port):
    class MyRequirer(CharmBase):
        def __init__(self, framework: Framework):
            super().__init__(framework)
            self.ipa = IngressPerAppRequirer(self, host=host, ip=ip, port=port)

    ctx = Context(
        charm_type=MyRequirer,
        meta={"name": "charlie", "requires": {"ingress": {"interface": "ingress"}}},
    )
    return ctx


@pytest.mark.parametrize(
    "port, ip, host", ((80, "1.1.1.1", "1.1.1.1"), (81, "10.1.10.1", "1.1.1.1"))
)
@pytest.mark.parametrize("evt_name", ("joined", "changed"))
@pytest.mark.parametrize("leader", (True, False))
def test_ingress_per_app_requirer_with_auto_data(host, ip, port, model, evt_name, leader):
    ipa = Relation("ingress")
    state = State(
        model=model,
        leader=leader,
        relations=[ipa],
    )
    requirer_ctx = get_requirer_ctx(host, ip, port)
    state_out = requirer_ctx.run(getattr(ipa, evt_name + "_event"), state)

    ipa_out = state_out.get_relations("ingress")[0]
    assert ipa_out.local_unit_data == {"host": json.dumps(host), "ip": json.dumps(ip)}

    if leader:
        assert ipa_out.local_app_data == {
            "model": '"test-model"',
            "name": '"charlie"',
            "port": str(port),
            "redirect-https": "false",
            "scheme": '"http"',
            "strip-prefix": "false",
        }


def test_ingress_per_app_cleanup_on_remove(model, traefik_ctx, traefik_container):
    """Check that config file is removed when a relation is."""
    ipa = create_ingress_relation()

    td = tempfile.TemporaryDirectory()
    filename = f"juju_ingress_ingress_{ipa.relation_id}_remote.yaml"
    conf_file = Path(td.name).joinpath(filename)
    conf_file.write_text("foobar")

    traefik_container = traefik_container.replace(mounts={"conf": Mount("/opt/traefik/", td.name)})

    state = State(
        model=model,
        config={"routing_mode": "path", "external_hostname": "foo.com"},
        containers=[traefik_container],
        relations=[ipa],
    )

    # WHEN the relation goes
    traefik_ctx.run(ipa.broken_event, state)

    # THEN the config file was deleted
    mock_dynamic_config_folder = traefik_container.get_filesystem(traefik_ctx).joinpath(
        "opt", "traefik", "juju", filename
    )
    assert not mock_dynamic_config_folder.exists()


@pytest.mark.parametrize("rel_id", (1, 2, 3))
@pytest.mark.parametrize("remote_app_name", ("remote", "distant"))
@pytest.mark.parametrize("strip_prefix", (True, False))
@pytest.mark.parametrize("redirect_https", (True, False))
def test_ingress_per_app_v1_upgrade_v2(
    model,
    rel_id,
    remote_app_name,
    strip_prefix,
    redirect_https,
):
    requirer_ctx = get_requirer_ctx("host", "1.2.3.4", 4242)

    ipav1 = Relation(
        "ingress",
        remote_app_name=remote_app_name,
        remote_app_data={"ingress": 'url: http://10.206.54.240/"openstack"-"keystone"\n'},
        local_app_data={"name": "robin", "host": "host", "port": "4242", "model": model.name},
    )

    state = State(
        leader=True,
        model=model,
        relations=[ipav1],
    )

    # WHEN a charm upgrade occurs
    with requirer_ctx.manager("upgrade-charm", state) as mgr:
        assert not mgr.charm.ipa.is_ready()
        state_out = mgr.run()
        assert not mgr.charm.ipa.is_ready()

    # THEN the relation databags are upgraded to match the v2 spec
    ingress_out = state_out.get_relations("ingress")[0]
    IngressRequirerUnitData.load(ingress_out.local_unit_data)
    IngressRequirerAppData.load(ingress_out.local_app_data)
