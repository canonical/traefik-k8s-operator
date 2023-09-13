import json

import pytest
from charms.traefik_k8s.v2.ingress import (
    IngressProviderAppData,
    IngressRequirerAppData,
    IngressRequirerUnitData,
)


@pytest.mark.parametrize("clear", (True, False))
def test_io_ingress_requirer_unit_data(clear):
    databag = {"kaboom": '"boom"'}
    unit_data = IngressRequirerUnitData(host="foo.com")

    unit_data.dump(databag, clear=clear)
    expected = {
        "host": '"foo.com"',
    }
    if not clear:
        expected["kaboom"] = '"boom"'

    assert databag == expected

    assert IngressRequirerUnitData.load(databag) == unit_data


def test_io_ingress_requirer_app_data():
    databag = {}
    app_data = IngressRequirerAppData(port=10, name="foo", model="coslite", strip_prefix=True)

    app_data.dump(databag)
    assert databag == {
        k: json.dumps(v)
        for k, v in {
            "model": "coslite",
            "port": 10,
            "name": "foo",
            "strip-prefix": True,
            "redirect-https": None,
            "scheme": "http",
        }.items()
    }
    assert IngressRequirerAppData.load(databag) == app_data


def test_aliases():
    databag = {}
    app_data = IngressRequirerAppData(
        port=10,
        name="foo",
        model="coslite",
        strip_prefix=True,
        redirect_https=True,
    )

    app_data.dump(databag)
    assert databag == {
        k: json.dumps(v)
        for k, v in {
            "model": "coslite",
            "name": "foo",
            "port": 10,
            "strip-prefix": True,
            "redirect-https": True,
            "scheme": "http",
        }.items()
    }

    assert IngressRequirerAppData.load(databag) == app_data


def test_io_provider_data():
    databag = {}
    url = {"url": "https://foo.com"}
    app_data = IngressProviderAppData(ingress=url)

    app_data.dump(databag)
    assert databag == {"ingress": json.dumps(url)}

    assert IngressProviderAppData.load(databag) == app_data
