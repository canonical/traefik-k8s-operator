import json

import pytest
from charms.traefik_k8s.v2.ingress import (
    IngressProviderAppData,
    IngressRequirerAppData,
    IngressRequirerUnitData,
)


@pytest.mark.parametrize("clear", (True, False))
def test_io_ingress_requirer_unit_data(clear):
    """Verify the 'clear' functionality of classes inheriting from DatabagModel.

    Verify that if clear=True, when .dump()'ing data, any existing data in the databag is wiped;
    else, it is kept.
    """
    databag = {"kaboom": '"boom"'}
    unit_data = IngressRequirerUnitData(host="foo.com", ip="10.0.0.1")

    unit_data.dump(databag, clear=clear)
    expected = {"host": '"foo.com"', "ip": '"10.0.0.1"'}
    if not clear:
        expected["kaboom"] = '"boom"'

    assert databag == expected

    assert IngressRequirerUnitData.load(databag) == unit_data


def test_io_ingress_requirer_app_data():
    """Round trip test: A.dump().load() == A for A = IngressRequirerAppData."""
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
    """Verify the pydantic aliasing functionality: pass 'strip_prefix', dump 'strip-prefix'."""
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
    """Round trip test: A.dump().load() == A for A = IngressProviderAppData."""
    databag = {}
    url = {"url": "https://foo.com"}
    app_data = IngressProviderAppData(ingress=url)

    app_data.dump(databag)
    assert databag == {"ingress": json.dumps(url)}

    assert IngressProviderAppData.load(databag) == app_data
