import json

from charms.traefik_k8s.v2.ingress import (
    IngressProviderAppData,
    IngressRequirerAppData,
    IngressRequirerUnitData,
)


def test_io_ingress_requirer_unit_data():
    databag = {}
    unit_data = IngressRequirerUnitData(port=10, host="foo.com")

    unit_data.dump(databag)
    assert databag == {
        "port": "10",
        "host": "foo.com",
    }

    assert IngressRequirerUnitData.load(databag) == unit_data


def test_io_ingress_requirer_app_data():
    databag = {}
    app_data = IngressRequirerAppData(name="foo", model="coslite", strip_prefix=True)

    app_data.dump(databag)
    assert databag == {"model": "coslite", "name": "foo", "strip-prefix": "true"}
    assert IngressRequirerAppData.load(databag) == app_data


def test_aliases():
    databag = {}
    app_data = IngressRequirerAppData(
        name="foo", model="coslite", strip_prefix=True, redirect_https=True, by_alias=False
    )

    app_data.dump(databag)
    assert databag == {
        "model": "coslite",
        "name": "foo",
        "strip-prefix": "true",
        "redirect-https": "true",
    }

    assert IngressRequirerAppData.load(databag) == app_data


def test_io_provider_data():
    databag = {}
    url = {"url": "https://foo.com"}
    app_data = IngressProviderAppData(ingress=url)

    app_data.dump(databag)
    assert databag == {"ingress": json.dumps(url)}

    assert IngressProviderAppData.load(databag) == app_data
