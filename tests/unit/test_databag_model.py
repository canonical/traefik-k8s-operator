import pydantic
import pytest

from charms.traefik_k8s.v2.ingress import IngressRequirerAppData


def test_round_trip():
    db = {}
    model = IngressRequirerAppData(
        model="foo",
        name="bar",
        port=10,
        strip_prefix=True,
        redirect_https=False,
        scheme="https"
    )
    model.dump(db)

    assert db == {''
                  'model': 'foo',
                  'name': 'bar',
                  'port': '10',
                  'redirect-https': 'false',
                  'scheme': 'https',
                  'strip-prefix': 'true'
                  }

    res = IngressRequirerAppData.load(db)
    assert res == model


def test_invalid_model():
    with pytest.raises(pydantic.ValidationError):
        IngressRequirerAppData(
            model="foo",
            name=10,
            port="asdasder",
            scheme="bubble"
        )


def test_extra_fields():
    with pytest.raises(pydantic.ValidationError) as r:
        IngressRequirerAppData(
            model="foo",
            name="bar",
            port=10,
            strip_prefix=True,
            redirect_https=False,
            scheme="https",
            qux="floz"
        )
