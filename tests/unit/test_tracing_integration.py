import os
from unittest.mock import patch

import opentelemetry
import pytest
import yaml
from charms.tempo_coordinator_k8s.v0.charm_tracing import (
    CHARM_TRACING_ENABLED,
    charm_tracing_disabled,
)
from charms.tempo_coordinator_k8s.v0.tracing import ProtocolType, Receiver, TracingProviderAppData
from scenario import Relation, State

from traefik import STATIC_CONFIG_PATH


@pytest.fixture
def charm_tracing_relation():
    db = {}
    TracingProviderAppData(
        receivers=[
            Receiver(
                url="http://foo.com:81",
                protocol=ProtocolType(name="otlp_http", type="http"),
            )
        ]
    ).dump(db)
    tracing = Relation("charm-tracing", remote_app_data=db)
    return tracing


@pytest.fixture
def workload_tracing_relation():
    workload_db = {}
    TracingProviderAppData(
        receivers=[
            Receiver(
                url="http://foo.com:14238",
                protocol=ProtocolType(name="jaeger_thrift_http", type="http"),
            )
        ]
    ).dump(workload_db)
    workload_tracing = Relation("workload-tracing", remote_app_data=workload_db)
    return workload_tracing


@pytest.mark.xfail(
    reason="Intermittent failure, see https://github.com/canonical/traefik-k8s-operator/issues/519"
)
def test_charm_trace_collection(traefik_ctx, traefik_container, caplog, charm_tracing_relation):
    # GIVEN the presence of a tracing relation

    state_in = State(relations=[charm_tracing_relation], containers=[traefik_container])

    # THEN we get some traces
    with patch(
        "opentelemetry.exporter.otlp.proto.http.trace_exporter.OTLPSpanExporter.export"
    ) as f:
        f.return_value = opentelemetry.sdk.trace.export.SpanExportResult.SUCCESS
        os.environ[CHARM_TRACING_ENABLED] = "1"
        # WHEN traefik receives <any event>
        traefik_ctx.run(charm_tracing_relation.changed_event, state_in)

    # assert "Setting up span exporter to endpoint: foo.com:81" in caplog.text
    # assert "Starting root trace with id=" in caplog.text
    span = f.call_args_list[0].args[0][0]
    assert span.resource.attributes["service.name"] == "traefik-k8s-charm"
    assert span.resource.attributes["compose_service"] == "traefik-k8s-charm"
    assert span.resource.attributes["charm_type"] == "TraefikIngressCharm"


def test_traefik_tracing_config(traefik_ctx, traefik_container, workload_tracing_relation):
    state_in = State(relations=[workload_tracing_relation], containers=[traefik_container])

    with charm_tracing_disabled():
        traefik_ctx.run(workload_tracing_relation.changed_event, state_in)

    tracing_cfg = (
        traefik_container.get_filesystem(traefik_ctx).joinpath(STATIC_CONFIG_PATH[1:]).read_text()
    )
    cfg = yaml.safe_load(tracing_cfg)
    assert cfg["tracing"] == {
        "jaeger": {
            "collector": {
                "endpoint": "http://foo.com:14238/api/traces?format=jaeger.thrift",
            }
        }
    }


@pytest.mark.parametrize("was_present_before", (True, False))
def test_traefik_tracing_config_removed_if_relation_data_invalid(
    traefik_ctx, traefik_container, workload_tracing_relation, was_present_before
):
    if was_present_before:
        dt_path = traefik_container.mounts["/etc/traefik"].src.joinpath("traefik.yaml")
        if not dt_path.parent.exists():
            dt_path.parent.mkdir(parents=True)
        dt_path.write_text("foo")

    state_in = State(
        relations=[workload_tracing_relation.replace(remote_app_data={"foo": "bar"})],
        containers=[traefik_container],
    )

    with charm_tracing_disabled():
        traefik_ctx.run(workload_tracing_relation.changed_event, state_in)

    tracing_cfg = (
        traefik_container.get_filesystem(traefik_ctx).joinpath(STATIC_CONFIG_PATH[1:]).read_text()
    )
    cfg = yaml.safe_load(tracing_cfg)
    # assert tracing config is removed
    assert "tracing" not in cfg


@pytest.mark.parametrize("was_present_before", (True, False))
def test_traefik_tracing_config_removed_on_relation_broken(
    traefik_ctx, traefik_container, workload_tracing_relation, was_present_before
):
    if was_present_before:
        dt_path = traefik_container.mounts["/etc/traefik"].src.joinpath("traefik.yaml")
        if not dt_path.parent.exists():
            dt_path.parent.mkdir(parents=True)
        dt_path.write_text("foo")

    state_in = State(relations=[workload_tracing_relation], containers=[traefik_container])

    with charm_tracing_disabled():
        traefik_ctx.run(workload_tracing_relation.broken_event, state_in)

    tracing_cfg = (
        traefik_container.get_filesystem(traefik_ctx).joinpath(STATIC_CONFIG_PATH[1:]).read_text()
    )
    cfg = yaml.safe_load(tracing_cfg)
    # assert tracing config is removed
    assert "tracing" not in cfg
