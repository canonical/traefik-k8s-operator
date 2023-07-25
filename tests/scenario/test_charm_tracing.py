from unittest.mock import patch

import opentelemetry
from charms.tempo_k8s.v0.tracing import Ingester, TracingRequirerAppData
from scenario import Relation, State


def test_charm_trace_collection(traefik_ctx, traefik_container, caplog):
    # GIVEN the presence of a tracing relation
    db = {}
    TracingRequirerAppData(
        host="foo.com", ingesters=[Ingester(protocol="otlp_grpc", port=81)]
    ).dump(db)
    tracing = Relation("tracing", remote_app_data=db)
    state_in = State(relations=[tracing], containers=[traefik_container])

    # THEN we get some traces
    with patch("opentelemetry.exporter.otlp.proto.grpc.exporter.OTLPExporterMixin._export") as f:
        f.return_value = opentelemetry.sdk.metrics._internal.export.MetricExportResult.SUCCESS
        # WHEN traefik receives <any event>
        traefik_ctx.run(tracing.changed_event, state_in)

    assert "Setting up span exporter to endpoint: foo.com:81" in caplog.text
    assert "Starting root trace with id=" in caplog.text
    span = f.call_args_list[0].args[0][0]
    assert span.resource.attributes["service.name"] == "traefik-k8s"
    assert span.resource.attributes["compose_service"] == "traefik-k8s"
    assert span.resource.attributes["charm_type"] == "TraefikIngressCharm"
