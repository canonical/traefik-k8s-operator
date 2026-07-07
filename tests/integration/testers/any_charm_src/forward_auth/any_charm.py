# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""any-charm src-overwrite for the IAP requirer (forward-auth tester).

Requests ingress, configures auth-proxy with oathkeeper, and runs a simple
httpbin-like HTTP server via pebble.
"""

import logging
import os
import pathlib
import sys

import ops
from any_charm_base import AnyCharmBase
from ops.pebble import Layer

# Bootstrap: recreate nested package structure from flat lib files.
_src = pathlib.Path(os.path.dirname(__file__))

_ingress_dir = _src / "charms" / "traefik_k8s" / "v2"
_ingress_dir.mkdir(parents=True, exist_ok=True)
(_src / "charms" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "traefik_k8s" / "v2" / "__init__.py").touch(exist_ok=True)
_lib_src = _src / "_lib_ingress_v2.py"
_lib_dst = _ingress_dir / "ingress.py"
if _lib_src.exists() and not _lib_dst.exists():
    _lib_dst.write_text(_lib_src.read_text())

_auth_dir = _src / "charms" / "oathkeeper" / "v0"
_auth_dir.mkdir(parents=True, exist_ok=True)
(_src / "charms" / "oathkeeper" / "__init__.py").touch(exist_ok=True)
(_src / "charms" / "oathkeeper" / "v0" / "__init__.py").touch(exist_ok=True)
_auth_src = _src / "_lib_auth_proxy_v0.py"
_auth_dst = _auth_dir / "auth_proxy.py"
if _auth_src.exists() and not _auth_dst.exists():
    _auth_dst.write_text(_auth_src.read_text())

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
        self.framework.observe(
            self.on["any"].pebble_ready,
            self._on_pebble_ready,
        )
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
