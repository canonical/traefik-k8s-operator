import pytest
from traefik import StaticConfigMergeConflictError, static_config_deep_merge


@pytest.mark.parametrize(
    "input1, input2, output",
    (
        ({"foo": "bar"}, {"baz": "qux"}, {"foo": "bar", "baz": "qux"}),
        ({"foo": {"bar": "baz"}}, {"foo": {"baz": "qux"}}, {"foo": {"bar": "baz", "baz": "qux"}}),
        ({"foo": "bar"}, {"foo": "bar"}, {"foo": "bar"}),
        ({"foo": ["bar"]}, {"foo": ["bar"]}, {"foo": ["bar"]}),
        ({"foo": ["bar"]}, {"foo": ["bar", "baz"]}, StaticConfigMergeConflictError),
        ({"foo": ["bar"]}, {"foo": ["baz"]}, StaticConfigMergeConflictError),
        ({"foo": "bar"}, {"foo": "baz"}, StaticConfigMergeConflictError),
    ),
)
def test_deep_merge(input1, input2, output):
    if isinstance(output, type) and issubclass(output, Exception):
        with pytest.raises(output):
            static_config_deep_merge(input1, input2)
    else:
        assert static_config_deep_merge(input1, input2) == output
