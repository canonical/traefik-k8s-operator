import pytest
from scenario import Relation, State

from tests.scenario.conftest import MOCK_LB_ADDRESS


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
        config={"routing_mode": routing_mode},
        containers=[traefik_container],
    )

    state_out = traefik_ctx.run(ipu.changed_event, state)

    ipu_out = state_out.get_relations(ipu.endpoint)[0]

    local_app_data = ipu_out.local_app_data
    if not leader:
        assert not local_app_data
    else:
        if mode == "tcp":
            expected_url = f"{MOCK_LB_ADDRESS}:{port}"
        else:
            prefix = f"{model}-{remote_unit_name.replace('/', '-')}"
            if routing_mode == "path":
                expected_url = f"http://{MOCK_LB_ADDRESS}/{prefix}"
            else:
                expected_url = f"http://{prefix}.{MOCK_LB_ADDRESS}/"

        assert local_app_data == {"ingress": f"{remote_unit_name}:\n  url: {expected_url}\n"}
