# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import socket
import unittest
from unittest.mock import Mock, patch

import ops.testing
import yaml
from charm import _STATIC_CONFIG_PATH, TraefikIngressCharm
from ops.charm import ActionEvent
from ops.model import ActiveStatus, Application, BlockedStatus, Relation, WaitingStatus
from ops.pebble import PathError
from ops.testing import Harness

ops.testing.SIMULATE_CAN_CONNECT = True


def relate(harness: Harness, per_app_relation: bool = False) -> Relation:
    interface_name = "ingress" if per_app_relation else "ingress-per-unit"
    relation_id = harness.add_relation(interface_name, "remote")
    harness.add_relation_unit(relation_id, "remote/0")
    relation = harness.model.get_relation(interface_name, relation_id)
    requirer.relation = relation
    requirer.local_app = harness.charm.app
    return relation


def _requirer_provide_ingress_requirements(
    harness: Harness,
    port: int,
    relation: Relation,
    host=socket.getfqdn(),
    mode="http",
    strip_prefix: bool = False,
    per_app_relation: bool = False,
):
    # same as requirer.provide_ingress_requirements(port=port, host=host)s
    data = {
        "port": str(port),
        "host": host,
        "model": "test-model",
        "name": "remote/0",
        "mode": mode,
    }

    if strip_prefix:
        data["strip-prefix"] = "true"

    harness.update_relation_data(
        relation.id,
        "remote" if per_app_relation else "remote/0",
        data,
    )
    return data


class _RequirerMock:
    local_app: Application = None
    relation: Relation = None

    def is_ready(self):
        try:
            return bool(self.url)
        except:  # noqa
            return False

    @property
    def ingress(self):
        return yaml.safe_load(self.relation.data[self.local_app]["ingress"])

    @property
    def url(self):
        try:
            return self.ingress.get("url", "") or self.ingress["remote/0"]["url"]
        except:  # noqa
            return None

    @property
    def urls(self):
        try:
            return {unit_name: ingr_["url"] for unit_name, ingr_ in self.ingress.items()}
        except:  # noqa
            return {}


requirer = _RequirerMock()


class TestTraefikIngressCharm(unittest.TestCase):
    def setUp(self):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_service_get(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertTrue(self.harness.charm._traefik_service_running)

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        traefik_container = self.harness.charm.unit.get_container("traefik")
        try:
            yaml.safe_load(traefik_container.pull("/opt/traefik/juju").read())
            raise Exception("The previous line should have failed")
        except (IsADirectoryError, PathError):
            # If the directory did not exist, the method would have thrown
            # a FileNotFoundError instead.
            pass

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        relation = relate(self.harness)
        for strip_prefix in (False, True):
            with self.subTest():
                _requirer_provide_ingress_requirements(
                    harness=self.harness,
                    relation=relation,
                    host="10.1.10.1",
                    port=9000,
                    strip_prefix=strip_prefix,
                )

                traefik_container = self.harness.charm.unit.get_container("traefik")
                file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
                conf = yaml.safe_load(traefik_container.pull(file).read())

                middlewares = {
                    "middlewares": {
                        "juju-sidecar-noprefix-test-model-remote-0": {
                            "stripPrefix": {
                                "prefixes": ["/test-model-remote-0"],
                                "forceSlash": False,
                            }
                        }
                    }
                }

                expected = {
                    "http": {
                        "routers": {
                            "juju-test-model-remote-0-router": {
                                "entryPoints": ["web"],
                                "rule": "PathPrefix(`/test-model-remote-0`)",
                                "service": "juju-test-model-remote-0-service",
                            },
                            "juju-test-model-remote-0-router-tls": {
                                "entryPoints": ["websecure"],
                                "rule": "PathPrefix(`/test-model-remote-0`)",
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
                            "juju-test-model-remote-0-service": {
                                "loadBalancer": {"servers": [{"url": "http://10.1.10.1:9000"}]}
                            }
                        },
                    }
                }

                if strip_prefix:
                    expected["http"].update(middlewares)
                    expected["http"]["routers"]["juju-test-model-remote-0-router"].update(
                        {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
                    )
                    expected["http"]["routers"]["juju-test-model-remote-0-router-tls"].update(
                        {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
                    )

                self.assertEqual(conf, expected)

                self.assertEqual(
                    requirer.urls,
                    {"remote/0": "http://testhostname:80/test-model-remote-0"},
                )
                self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode_per_app(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        relation = relate(self.harness, per_app_relation=True)
        for strip_prefix in (False, True):
            with self.subTest():
                _requirer_provide_ingress_requirements(
                    harness=self.harness,
                    relation=relation,
                    host="foo.bar",
                    port=3000,
                    strip_prefix=strip_prefix,
                    per_app_relation=True,
                )

                traefik_container = self.harness.charm.unit.get_container("traefik")
                file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
                conf = yaml.safe_load(traefik_container.pull(file).read())

                middlewares = {
                    "middlewares": {
                        "juju-sidecar-noprefix-test-model-remote-0": {
                            "stripPrefix": {
                                "prefixes": ["/test-model-remote-0"],
                                "forceSlash": False,
                            }
                        }
                    }
                }

                expected = {
                    "http": {
                        "routers": {
                            "juju-test-model-remote-0-router": {
                                "entryPoints": ["web"],
                                "rule": "PathPrefix(`/test-model-remote-0`)",
                                "service": "juju-test-model-remote-0-service",
                            },
                            "juju-test-model-remote-0-router-tls": {
                                "entryPoints": ["websecure"],
                                "rule": "PathPrefix(`/test-model-remote-0`)",
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
                            "juju-test-model-remote-0-service": {
                                "loadBalancer": {"servers": [{"url": "http://foo.bar:3000"}]}
                            }
                        },
                    }
                }
                if strip_prefix:
                    expected["http"].update(middlewares)
                    expected["http"]["routers"]["juju-test-model-remote-0-router"].update(
                        {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
                    )
                    expected["http"]["routers"]["juju-test-model-remote-0-router-tls"].update(
                        {"middlewares": ["juju-sidecar-noprefix-test-model-remote-0"]},
                    )

                self.assertEqual(conf, expected)

                self.assertEqual(
                    requirer.url,
                    "http://testhostname:80/test-model-remote-0",
                )
                self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_with_gateway_address_from_config_and_subdomain_routing_mode_per_app(
        self,
    ):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config(
            {"external_hostname": "testhostname", "routing_mode": "subdomain"}
        )
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        relation = relate(self.harness, per_app_relation=True)
        for strip_prefix in (False, True):
            # in subdomain routing mode this should not have any effect
            with self.subTest():
                _requirer_provide_ingress_requirements(
                    harness=self.harness,
                    relation=relation,
                    host="foo.bar",
                    port=3000,
                    strip_prefix=strip_prefix,
                    per_app_relation=True,
                )

                traefik_container = self.harness.charm.unit.get_container("traefik")
                file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
                conf = yaml.safe_load(traefik_container.pull(file).read())

                expected = {
                    "http": {
                        "routers": {
                            "juju-test-model-remote-0-router": {
                                "entryPoints": ["web"],
                                "rule": "Host(`test-model-remote-0.testhostname`)",
                                "service": "juju-test-model-remote-0-service",
                            },
                            "juju-test-model-remote-0-router-tls": {
                                "entryPoints": ["websecure"],
                                "rule": "Host(`test-model-remote-0.testhostname`)",
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
                            "juju-test-model-remote-0-service": {
                                "loadBalancer": {"servers": [{"url": "http://foo.bar:3000"}]}
                            }
                        },
                    }
                }
                self.assertEqual(conf, expected)

                self.assertEqual(
                    requirer.url,
                    "http://test-model-remote-0.testhostname:80/",
                )
                self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_with_gateway_address_from_config_and_subdomain_routing_mode(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.update_config(
            {
                "external_hostname": "testhostname",
                "routing_mode": "subdomain",
            }
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        relation = relate(self.harness)
        for strip_prefix in (False, True):
            # in subdomain routing mode this should not have any effect
            with self.subTest():
                _requirer_provide_ingress_requirements(
                    harness=self.harness,
                    relation=relation,
                    host="10.1.10.1",
                    port=9000,
                    strip_prefix=strip_prefix,
                )

                traefik_container = self.harness.charm.unit.get_container("traefik")
                file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
                conf = yaml.safe_load(traefik_container.pull(file).read())

                expected = {
                    "http": {
                        "routers": {
                            "juju-test-model-remote-0-router": {
                                "entryPoints": ["web"],
                                "rule": "Host(`test-model-remote-0.testhostname`)",
                                "service": "juju-test-model-remote-0-service",
                            },
                            "juju-test-model-remote-0-router-tls": {
                                "entryPoints": ["websecure"],
                                "rule": "Host(`test-model-remote-0.testhostname`)",
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
                            "juju-test-model-remote-0-service": {
                                "loadBalancer": {"servers": [{"url": "http://10.1.10.1:9000"}]}
                            }
                        },
                    }
                }
                self.assertEqual(conf, expected)

                self.assertEqual(
                    requirer.urls,
                    {"remote/0": "http://test-model-remote-0.testhostname:80/"},
                )
                self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_no_leader_with_gateway_address_from_config_and_subdomain_routing_mode(
        self,
    ):
        """Test round-trip bootstrap and relation with a consumer."""
        # TODO Make parametric to avoid duplication with
        # test_pebble_ready_with_gateway_address_from_config_and_subdomain_routing_mode
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(False)
        self.harness.begin_with_initial_hooks()

        self.harness.update_config(
            {
                "external_hostname": "testhostname",
                "routing_mode": "subdomain",
            }
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        relation = relate(self.harness)
        for strip_prefix in (False, True):
            # in subdomain routing mode this should not have any effect
            with self.subTest():
                _requirer_provide_ingress_requirements(
                    harness=self.harness,
                    relation=relation,
                    host="10.1.10.1",
                    port=9000,
                    strip_prefix=strip_prefix,
                )

            traefik_container = self.harness.charm.unit.get_container("traefik")
            file = f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
            conf = yaml.safe_load(traefik_container.pull(file).read())

            expected = {
                "http": {
                    "routers": {
                        "juju-test-model-remote-0-router": {
                            "entryPoints": ["web"],
                            "rule": "Host(`test-model-remote-0.testhostname`)",
                            "service": "juju-test-model-remote-0-service",
                        },
                        "juju-test-model-remote-0-router-tls": {
                            "entryPoints": ["websecure"],
                            "rule": "Host(`test-model-remote-0.testhostname`)",
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
                        "juju-test-model-remote-0-service": {
                            "loadBalancer": {"servers": [{"url": "http://10.1.10.1:9000"}]}
                        }
                    },
                }
            }

            self.assertEqual(conf, expected)

            self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_bad_routing_mode_config_and_recovery(self):
        """Test round-trip bootstrap and relation with a consumer."""
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.harness.update_config(
            {
                "external_hostname": "testhostname",
                "routing_mode": "FOOBAR",
            }
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus("invalid routing mode: FOOBAR; see logs."),
        )

        self.harness.update_config(
            {
                "routing_mode": "path",
            }
        )

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_without_gateway_address(self):
        """Test that requirers do not get addresses until the gateway address is available."""
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

        self.harness.container_pebble_ready("traefik")

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        assert not requirer.is_ready()

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

    @patch("charm._get_loadbalancer_status", lambda **__: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_pebble_ready_with_joined_relations(self):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://10.0.0.1:80/test-model-remote-0"},
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **__: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_gateway_address_change_with_joined_relations(self):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        self.harness.container_pebble_ready("traefik")

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://10.0.0.1:80/test-model-remote-0"},
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.harness.update_config({"external_hostname": "testhostname"})

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://testhostname:80/test-model-remote-0"},
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_gateway_address_becomes_unavailable_after_relation_join(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )
        assert requirer.is_ready()

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://testhostname:80/test-model-remote-0"},
        )
        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

        self.harness.update_config(unset=["external_hostname"])

        self.assertEqual(
            self.harness.charm.unit.status, WaitingStatus("gateway address unavailable")
        )

        self.assertEqual(requirer.urls, {})

    def test_relation_broken(self):
        self.test_pebble_ready_with_gateway_address_from_config_and_path_routing_mode()

        relation = self.harness.model.relations["ingress-per-unit"][0]
        self.harness.remove_relation(relation.id)

        traefik_container = self.harness.charm.unit.get_container("traefik")

        try:
            traefik_container.pull(
                f"/opt/traefik/juju/juju_ingress_{relation.name}_{relation.id}_{relation.app.name}.yaml"
            ).read()
            raise Exception("The line above should fail")
        except (FileNotFoundError, PathError):
            pass

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.TraefikIngressCharm._traefik_service_running", lambda **__: True)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_show_proxied_endpoints_action_no_relations(self):
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        action_event = Mock(spec=ActionEvent)
        self.harness.update_config({"external_hostname": "foo"})
        self.harness.charm._on_show_proxied_endpoints(action_event)
        action_event.set_results.assert_called_once_with({"proxied-endpoints": "{}"})

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_show_proxied_endpoints_action_only_ingress_per_app_relations(self):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness, per_app_relation=True)
        _requirer_provide_ingress_requirements(
            harness=self.harness,
            relation=relation,
            host="10.0.0.1",
            port=3000,
            per_app_relation=True,
        )

        self.harness.container_pebble_ready("traefik")

        action_event = Mock(spec=ActionEvent)
        self.harness.charm._on_show_proxied_endpoints(action_event)
        action_event.set_results.assert_called_once_with(
            {
                "proxied-endpoints": json.dumps(
                    {"remote": {"url": "http://testhostname:80/test-model-remote-0"}}
                )
            }
        )

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_show_proxied_endpoints_action_only_ingress_per_unit_relations(self):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.0.0.1", port=3000
        )

        self.harness.container_pebble_ready("traefik")

        action_event = Mock(spec=ActionEvent)
        self.harness.charm._on_show_proxied_endpoints(action_event)
        action_event.set_results.assert_called_once_with(
            {
                "proxied-endpoints": json.dumps(
                    {"remote/0": {"url": "http://testhostname:80/test-model-remote-0"}}
                )
            }
        )

    @patch("charm._get_loadbalancer_status", lambda **__: None)
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def test_tcp_config(self):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        data = _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.0.0.1", port=3000, mode="tcp"
        )

        self.harness.container_pebble_ready("traefik")
        charm = self.harness.charm
        prefix = charm._get_prefix(data)
        expected_entrypoint = {"address": ":3000"}
        assert charm._tcp_entrypoints() == {prefix: expected_entrypoint}

        static_config = charm.unit.get_container("traefik").pull(_STATIC_CONFIG_PATH).read()
        assert yaml.safe_load(static_config)["entryPoints"][prefix] == expected_entrypoint


class TestConfigOptionsValidation(unittest.TestCase):
    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda *_, **__: None)
    def setUp(self):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=self.relation, host="10.1.10.1", port=9000
        )

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **_: None)
    def test_when_external_hostname_not_set_use_ip_with_port_80(self):
        self.assertEqual(requirer.urls, {"remote/0": "http://10.0.0.1:80/test-model-remote-0"})

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **_: None)
    def test_when_external_hostname_is_set_use_it_with_port_80(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(requirer.urls, {"remote/0": "http://testhostname:80/test-model-remote-0"})

    @patch("charm._get_loadbalancer_status", lambda **_: "10.0.0.1")
    @patch("charm.KubernetesServicePatch", lambda **_: None)
    def test_when_external_hostname_is_invalid_go_into_blocked_status(self):
        for invalid_hostname in [
            "testhostname:8080",
            "user:pass@testhostname",
            "testhostname/prefix",
        ]:
            with self.subTest(invalid_hostname=invalid_hostname):
                self.harness.update_config({"external_hostname": invalid_hostname})
                self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)
                self.assertEqual(requirer.urls, {})
