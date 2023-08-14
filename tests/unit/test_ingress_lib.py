import json

from charms.traefik_k8s.v2.ingress import (
    IngressProviderAppData,
    IngressRequirerAppData,
    IngressRequirerUnitData,
)


def test_io_ingress_requirer_unit_data():
    databag = {}
    unit_data = IngressRequirerUnitData(host="foo.com", ip="10.0.0.1")

    unit_data.dump(databag)
    assert databag == {"host": '"foo.com"', "ip": '"10.0.0.1"'}

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
