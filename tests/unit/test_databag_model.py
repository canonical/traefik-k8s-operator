import json

import pydantic
import pytest
from charms.traefik_k8s.v2.ingress import IngressRequirerAppData, IngressRequirerUnitData


def test_round_trip():
    db = {}
    model = IngressRequirerAppData(
        model="foo", name="bar", port=10, strip_prefix=True, redirect_https=False, scheme="https"
    )
    model.dump(db)

    assert db == {
        "model": json.dumps("foo"),
        "name": json.dumps("bar"),
        "port": json.dumps(10),
        "redirect-https": json.dumps(False),
        "scheme": json.dumps("https"),
        "strip-prefix": json.dumps(True),
    }

    res = IngressRequirerAppData.load(db)
    assert res == model

    assert res.model == "foo"
    assert res.port == 10
    assert res.strip_prefix is True


def test_deserialize_raw():
    remote_unit_data = {"host": '"foo"', "ip": '"10.0.0.1"'}
    data = IngressRequirerUnitData.load(remote_unit_data)
    assert data.host == "foo"


def test_invalid_model():
    with pytest.raises(pydantic.ValidationError):
        IngressRequirerAppData(model="foo", name=10, port="asdasder", scheme="bubble")


def test_extra_fields():
    IngressRequirerAppData(
        model="foo",
        name="bar",
        port=10,
        strip_prefix=True,
        redirect_https=False,
        scheme="https",
        qux="floz",
    )
