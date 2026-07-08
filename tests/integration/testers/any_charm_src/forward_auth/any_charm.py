# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for the IAP requirer (forward-auth tester).

Requests ingress, configures auth-proxy with oathkeeper, and runs a simple
httpbin-like HTTP server via pebble.
"""

import logging
import pathlib
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.pebble import Layer

_src = pathlib.Path(__file__).parent
sys.path.insert(0, str(_src))

from charms.oathkeeper.v0.auth_proxy import AuthProxyConfig, AuthProxyRequirer  # noqa: E402
from charms.traefik_k8s.v2.ingress import IngressPerAppRequirer  # noqa: E402

logger = logging.getLogger(__name__)

AUTH_PROXY_ALLOWED_ENDPOINTS = ["anything/allowed"]
AUTH_PROXY_HEADERS = ["X-User"]
HTTPBIN_PORT = 80


class AnyCharm(AnyCharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ingress = IngressPerAppRequirer(
            self,
            host=f"{self.app.name}.{self.model.name}.svc.cluster.local",
            relation_name="require-ingress",
            port=HTTPBIN_PORT,
            strip_prefix=True,
        )
        self.auth_proxy = AuthProxyRequirer(
            self, self._auth_proxy_config, "require-auth-proxy"
        )
        self.framework.observe(self.on["any"].pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.ingress.on.ready, self._on_ingress_ready)

    @property
    def _auth_proxy_config(self):
        return AuthProxyConfig(
            protected_urls=[
                self.ingress.url
                if self.ingress.url is not None
                else "https://some-test-url.com"
            ],
            headers=AUTH_PROXY_HEADERS,
            allowed_endpoints=AUTH_PROXY_ALLOWED_ENDPOINTS,
        )

    def _on_pebble_ready(self, event):
        container = event.workload
        # Install python3 in the minimal workload container
        container.exec(["apt-get", "update", "-qq"]).wait()
        container.exec(["apt-get", "install", "-y", "-qq", "python3"]).wait()
        # Push the server script to the workload container
        server_script = (_src / "httpbin_server.py").read_text()
        container.push("/httpbin_server.py", server_script, make_dirs=True)
        layer = Layer({
            "summary": "httpbin layer",
            "services": {
                "httpbin": {
                    "override": "replace",
                    "command": "python3 /httpbin_server.py",
                    "startup": "enabled",
                }
            },
        })
        container.add_layer("httpbin", layer, combine=True)
        container.replan()
        self.unit.open_port(protocol="tcp", port=HTTPBIN_PORT)
        self.unit.status = ops.ActiveStatus()

    def _on_ingress_ready(self, event):
        if self.unit.is_leader():
            logger.info(f"This app's ingress URL: {event.url}")
        self.auth_proxy.update_auth_proxy_config(
            auth_proxy_config=self._auth_proxy_config
        )
