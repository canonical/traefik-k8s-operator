from unittest.mock import patch

import opentelemetry
import pytest
import yaml
from charm import _CA_CERT_PATH, _DYNAMIC_TRACING_PATH
from charms.tempo_k8s.v0.charm_tracing import charm_tracing_disabled
from charms.tempo_k8s.v0.tracing import Ingester, TracingProviderAppData
from scenario import Relation, State


@pytest.fixture
def tracing_relation():
    db = {}
    TracingProviderAppData(
        host="foo.com", ingesters=[Ingester(protocol="otlp_grpc", port=81)]
    ).dump(db)
    tracing = Relation("tracing", remote_app_data=db)
    return tracing


def test_charm_trace_collection(traefik_ctx, traefik_container, caplog, tracing_relation):
    # GIVEN the presence of a tracing relation

    state_in = State(relations=[tracing_relation], containers=[traefik_container])

    # THEN we get some traces
    with patch("opentelemetry.exporter.otlp.proto.grpc.exporter.OTLPExporterMixin._export") as f:
        f.return_value = opentelemetry.sdk.metrics._internal.export.MetricExportResult.SUCCESS
        # WHEN traefik receives <any event>
        traefik_ctx.run(tracing_relation.changed_event, state_in)

    assert "Setting up span exporter to endpoint: foo.com:81" in caplog.text
    assert "Starting root trace with id=" in caplog.text
    span = f.call_args_list[0].args[0][0]
    assert span.resource.attributes["service.name"] == "traefik-k8s"
    assert span.resource.attributes["compose_service"] == "traefik-k8s"
    assert span.resource.attributes["charm_type"] == "TraefikIngressCharm"


def test_traefik_tracing_config(traefik_ctx, traefik_container, tracing_relation):
    state_in = State(relations=[tracing_relation], containers=[traefik_container])

    with charm_tracing_disabled():
        traefik_ctx.run(tracing_relation.changed_event, state_in)

    tracing_cfg = (
        traefik_container.get_filesystem(traefik_ctx)
        .joinpath(_DYNAMIC_TRACING_PATH[1:])
        .read_text()
    )
    cfg = yaml.safe_load(tracing_cfg)
    assert cfg == {
        "tracing": {
            "openTelemetry": {
                "address": "foo.com:81",
                "grpc": {},
                "insecure": True,
            }
        }
    }


def test_traefik_tracing_config_with_tls(traefik_ctx, traefik_container, tracing_relation):
    state_in = State(relations=[tracing_relation], containers=[traefik_container])

    with patch("charm.TraefikIngressCharm._is_tls_enabled") as tls_enabled:
        tls_enabled.return_value = "True"

        with charm_tracing_disabled():
            traefik_ctx.run(tracing_relation.changed_event, state_in)

    tracing_cfg = (
        traefik_container.get_filesystem(traefik_ctx)
        .joinpath(_DYNAMIC_TRACING_PATH[1:])
        .read_text()
    )
    cfg = yaml.safe_load(tracing_cfg)
    assert cfg == {
        "tracing": {
            "openTelemetry": {
                "address": "foo.com:81",
                "grpc": {},
                "ca": _CA_CERT_PATH,
            }
        }
    }


@pytest.mark.parametrize("was_present_before", (True, False))
def test_traefik_tracing_config_removed_if_relation_data_invalid(
    traefik_ctx, traefik_container, tracing_relation, was_present_before
):
    if was_present_before:
        dt_path = traefik_container.mounts["opt"].src.joinpath("traefik", "juju", "tracing.yaml")
        dt_path.parent.mkdir(parents=True)
        dt_path.write_text("foo")

    state_in = State(
        relations=[tracing_relation.replace(remote_app_data={"foo": "bar"})],
        containers=[traefik_container],
    )

    with charm_tracing_disabled():
        traefik_ctx.run(tracing_relation.changed_event, state_in)

    # assert file is not there
    assert (
        not traefik_container.get_filesystem(traefik_ctx).joinpath(_DYNAMIC_TRACING_PATH).exists()
    )


@pytest.mark.parametrize("was_present_before", (True, False))
def test_traefik_tracing_config_removed_on_relation_broken(
    traefik_ctx, traefik_container, tracing_relation, was_present_before
):
    if was_present_before:
        dt_path = traefik_container.mounts["opt"].src.joinpath("traefik", "juju", "tracing.yaml")
        dt_path.parent.mkdir(parents=True)
        dt_path.write_text("foo")

    state_in = State(relations=[tracing_relation], containers=[traefik_container])

    with charm_tracing_disabled():
        traefik_ctx.run(tracing_relation.broken_event, state_in)

    # assert file is not there
    assert (
        not traefik_container.get_filesystem(traefik_ctx).joinpath(_DYNAMIC_TRACING_PATH).exists()
    )
