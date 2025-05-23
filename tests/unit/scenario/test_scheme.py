#
# TODO: implement
# @pytest.mark.parametrize("scheme", ("http", "https", "h2c"))
# def test_scheme(traefik_ctx, scheme, traefik_container):
#     ipa = Relation(
#         "ingress",
#         remote_app_data={
#             "model": "test-model",
#             "name": "remote",
#             "port": "42",
#             "scheme": scheme,
#         },
#         remote_units_data={
#             1: {"host": "foobar.com"}
#         },
#     )
#     state_in = State(
#         config={"routing_mode": "path", "external_hostname": "foo.com"},
#         containers=[traefik_container],
#         relations=[ipa],
#     )
#
#
#
# @pytest.mark.parametrize("scheme", ("foo", "bar", "1"))
# def test_invalid_scheme(scheme):
#     pass
