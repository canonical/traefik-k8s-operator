import json

import pydantic
import pytest
from charms.traefik_k8s.v2.ingress import IngressRequirerAppData, IngressRequirerUnitData
from pydantic import ConfigDict


@pytest.mark.parametrize("nest_under", (True, False))
def test_round_trip(nest_under):
    if nest_under:
        if pydantic.version.VERSION.split(".") <= ["2"]:

            class MyAppData(IngressRequirerAppData):
                _NEST_UNDER = "config"

        else:

            class MyAppData(IngressRequirerAppData):
                model_config = ConfigDict(_NEST_UNDER="config")

    else:

        class MyAppData(IngressRequirerAppData):
            pass

    cfg = {
        "model": "foo",
        "name": "bar",
        "port": 10,
        "strip_prefix": True,
        "scheme": "https",
    }
    aliased = {k.replace("_", "-"): v for k, v in cfg.items()}
    db = {}
    model = MyAppData(**cfg)
    model.dump(db)

    if nest_under:
        if pydantic.version.VERSION.split(".") <= ["2"]:
            assert db == {"config": json.dumps(aliased)}
        else:
            assert db == {"config": json.dumps(aliased, separators=(",", ":"))}

    else:
        assert db == {k: json.dumps(v) for k, v in aliased.items()}

    res = MyAppData.load(db)
    assert res == model

    assert res.model == "foo"
    assert res.port == 10
    assert res.strip_prefix is True

    if not nest_under:
        assert "config" not in db
    if nest_under:
        assert "model" not in db


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
