import os
from pathlib import Path

from theatre.main import show_main_window

show_main_window(Path(os.getcwd()))

# DEMO

# deltas:

from scenario import *

from charms.traefik_k8s.v2.ingress import IngressRequirerAppData, IngressRequirerUnitData


def with_ingress(state: State) -> State:
    return state.replace(
        containers=[Container(
            'traefik',
            can_connect=True,
            exec_mock={('update-ca-certificates', '--fresh'): ExecOutput()})
        ],
        relations=[
            Relation(
                "ingress",
                remote_app_data=IngressRequirerAppData(model="foo", name="bar", port=42).dump(),
                remote_units_data={
                    1: IngressRequirerUnitData(host="goo.com").dump()}
            )
        ]
    )
