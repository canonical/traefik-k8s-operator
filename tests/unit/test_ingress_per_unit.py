import pytest
from scenario import Relation, State


@pytest.mark.parametrize("leader", (True, False))
@pytest.mark.parametrize("url", ("url.com", "http://foo.bar.baz"))
@pytest.mark.parametrize("mode", ("tcp", "http"))
@pytest.mark.parametrize("remote_unit_name", ("remote/0", "remote/42"))
@pytest.mark.parametrize("model", ("modela", "modelb"))
@pytest.mark.parametrize("routing_mode", ("path", "subdomain"))
@pytest.mark.parametrize("port, host", ((80, "1.1.1.1"), (81, "10.1.10.1")))
def test_ingress_unit_provider_request_response(
    traefik_ctx,
    traefik_container,
    routing_mode,
    remote_unit_name,
    model,
    port,
    host,
    leader,
    url,
    mode,
):
    mock_data = {
        "port": str(port),
        "host": host,
        "model": model,
        "name": remote_unit_name,
        "mode": mode,
    }
    ipu = Relation(endpoint="ingress-per-unit", remote_units_data={0: mock_data})

    state = State(
        relations=[ipu],
        leader=leader,
        config={"routing_mode": routing_mode, "external_hostname": "example.com"},
        containers=[traefik_container],
    )

    state_out = traefik_ctx.run(ipu.changed_event, state)

    ipu_out = state_out.get_relations(ipu.endpoint)[0]

    local_app_data = ipu_out.local_app_data
    if not leader:
        assert not local_app_data
    else:
        if mode == "tcp":
            expected_url = f"example.com:{port}"
        else:
            prefix = f"{model}-{remote_unit_name.replace('/', '-')}"
            if routing_mode == "path":
                expected_url = f"http://example.com/{prefix}"
            else:
                expected_url = f"http://{prefix}.example.com/"

        assert local_app_data == {"ingress": f"{remote_unit_name}:\n  url: {expected_url}\n"}


def test_proxied_endpoints_partial_readiness(
    traefik_ctx, traefik_container
):
    """Test that proxied_endpoints returns only healthy relations when some aren't ready."""
    ready_data = {
        "port": "80",
        "host": "1.1.1.1",
        "model": "test-model",
        "name": "ready-app/0",
        "mode": "tcp",
    }

    ready_relation = Relation(
        endpoint="ingress-per-unit",
        remote_app_name="ready-app",
        relation_id=1,
        remote_units_data={0: ready_data},
    )
    not_ready_relation = Relation(
        endpoint="ingress-per-unit",
        remote_app_name="not-ready-app",
        relation_id=2,
        remote_units_data={0: {}},
    )

    state = State(
        leader=True,
        relations=[ready_relation, not_ready_relation],
        config={"routing_mode": "path", "external_hostname": "example.com"},
        containers=[traefik_container],
    )

    with traefik_ctx.manager("update-status", state) as mgr:
        charm = mgr.charm

        charm.ingress_per_unit.publish_url(
            charm.model.get_relation("ingress-per-unit", ready_relation.relation_id),
            "ready-app/0",
            "http://ready-app.com",
        )
        # Don't publish URL for not_ready_relation

        endpoints = charm.ingress_per_unit.proxied_endpoints

        assert len(endpoints) == 1
        assert "ready-app/0" in endpoints
        assert endpoints["ready-app/0"]["url"] == "http://ready-app.com"
