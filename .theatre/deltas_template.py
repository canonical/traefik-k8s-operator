from scenario import *
from ops import pebble
from charms.traefik_k8s.v2.ingress import IngressRequirerAppData, IngressRequirerUnitData


def with_ingress(state: State) -> State:
    return state.replace(
        containers=[Container(
            'traefik',
            can_connect=True,
            layers={"traefik": pebble.Layer({"services": {"traefik": {"startup": "enabled"}}})},
            service_status={
                "traefik": pebble.ServiceStatus.ACTIVE
            },
            exec_mock={('update-ca-certificates', '--fresh'): ExecOutput()})
        ],
        relations=[
            Relation(
                "ingress",
                remote_app_data=IngressRequirerAppData(
                    host="goo.com", model="foo", name="bar", port=42
                ).dump(),
                remote_units_data={
                    1: IngressRequirerUnitData(host="goo.com").dump()}
            )
        ]
    )
