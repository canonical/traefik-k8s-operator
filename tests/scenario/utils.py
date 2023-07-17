def _render_middlewares(*, strip_prefix: bool = False, redirect_https: bool = False) -> dict:
    middlewares = {}
    if redirect_https:
        middlewares.update({"redirectScheme": {"scheme": "https", "port": 443, "permanent": True}})
    if strip_prefix:
        middlewares.update(
            {
                "stripPrefix": {
                    "prefixes": ["/test-model-remote-0"],
                    "forceSlash": False,
                }
            }
        )
    return (
        {"middlewares": {"juju-sidecar-noprefix-test-model-remote-0": middlewares}}
        if middlewares
        else {}
    )


def _render_config(
        *, rel_name: str, routing_mode: str, strip_prefix: bool, redirect_https: bool, scheme: str = 'http',
        tls_enabled: bool = True
):
    routing_rule = {
        "path": "PathPrefix(`/test-model-remote-0`)",
        "subdomain": "Host(`test-model-remote-0.testhostname`)",
    }

    if rel_name != "ingress":
        scheme = "http"
        # ipu does not do https for now

    service_spec = {
        "loadBalancer": {"servers": [{"url": f"{scheme}://10.1.10.1:9000"}]},
    }
    if scheme == 'https' and tls_enabled:
        service_spec["rootCAs"] = ["/opt/traefik/juju/certificate.cert"]

    expected = {
        "http": {
            "routers": {
                "juju-test-model-remote-0-router": {
                    "entryPoints": ["web"],
                    "rule": routing_rule[routing_mode],
                    "service": "juju-test-model-remote-0-service",
                },
                "juju-test-model-remote-0-router-tls": {
                    "entryPoints": ["websecure"],
                    "rule": routing_rule[routing_mode],
                    "service": "juju-test-model-remote-0-service",
                    "tls": {
                        "domains": [
                            {
                                "main": "testhostname",
                                "sans": ["*.testhostname"],
                            },
                        ],
                    },
                },
            },
            "services": {
                "juju-test-model-remote-0-service": service_spec
            },
        }
    }

    if middlewares := _render_middlewares(
            strip_prefix=strip_prefix and routing_mode == "path", redirect_https=redirect_https
    ):
        expected["http"].update(middlewares)
        expected["http"]["routers"]["juju-test-model-remote-0-router"].update(
            {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
        )
        expected["http"]["routers"]["juju-test-model-remote-0-router-tls"].update(
            {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
        )

    return expected
