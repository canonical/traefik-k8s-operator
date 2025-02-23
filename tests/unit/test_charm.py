# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import socket
import unittest
from unittest.mock import Mock, PropertyMock, patch

import ops.testing
import yaml
from charms.traefik_k8s.v2.ingress import IngressRequirerAppData, IngressRequirerUnitData
from ops.charm import ActionEvent
from ops.model import ActiveStatus, Application, BlockedStatus, Relation
from ops.pebble import PathError
from ops.testing import Harness

from charm import TraefikIngressCharm
from traefik import STATIC_CONFIG_PATH

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
    ip=socket.gethostbyname(socket.gethostname()),
    mode="http",
    strip_prefix: bool = False,
    redirect_https: bool = False,
    per_app_relation: bool = False,
):
    if per_app_relation:
        app_data = IngressRequirerAppData(
            model="test-model",
            name="remote/0",
            port=port,
            redirect_https=redirect_https,
            strip_prefix=strip_prefix,
        ).dump()
        unit_data = IngressRequirerUnitData(host=host, ip=ip).dump()
        # do not emit this event, as we need to 'simultaneously'
        # update the remote unit and app databags
        with harness.hooks_disabled():
            harness.update_relation_data(relation.id, "remote/0", unit_data)

    else:
        # same as requirer.provide_ingress_requirements(port=port, host=host)s
        app_data = {
            "model": "test-model",
            "name": "remote/0",
            "mode": mode,
            "port": str(port),
            "host": host,
            # Must set these to something, because when used with subTest, the previous relation data
            # must be overwritten: if a key is omitted, then a plain `update` would keep existing keys.
            # TODO also need to test what happens when any of these is not specified at all
            "strip-prefix": "true" if strip_prefix else "false",
            "redirect-https": "true" if redirect_https else "false",
        }

    harness.update_relation_data(
        relation.id,
        "remote" if per_app_relation else "remote/0",
        app_data,
    )
    return app_data


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
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)
        self.harness.handle_exec(
            "traefik", ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"], result=0
        )

        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)

    def test_service_get(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("traefik")

        self.assertTrue(self.harness.charm.traefik.is_ready)

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

        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_pebble_ready_without_gateway_address(self, mock_get_loadbalancer_status):
        """Test that requirers do not get addresses until the gateway address is available."""
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus(
                "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
            ),
        )

        self.harness.container_pebble_ready("traefik")

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        assert not requirer.is_ready()

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus(
                "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
            ),
        )

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def test_pebble_ready_with_joined_relations(self, mock_get_loadbalancer_status):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        self.harness.container_pebble_ready("traefik")

        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://10.0.0.1/test-model-remote-0"},
        )
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def test_gateway_address_change_with_joined_relations(self, mock_get_loadbalancer_status):
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.1.10.1", port=9000
        )

        self.harness.container_pebble_ready("traefik")

        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://10.0.0.1/test-model-remote-0"},
        )
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        self.harness.update_config({"external_hostname": "testhostname"})

        self.assertEqual(
            requirer.urls,
            {"remote/0": "http://testhostname/test-model-remote-0"},
        )
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_gateway_address_becomes_unavailable_after_relation_join(
        self, mock_get_loadbalancer_status
    ):
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
            {"remote/0": "http://testhostname/test-model-remote-0"},
        )
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

        self.harness.update_config(unset=["external_hostname"])

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus(
                "Traefik load balancer is unable to obtain an IP or hostname from the cluster."
            ),
        )

        self.assertEqual(requirer.urls, {})

    def test_relation_broken(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        relation = relate(self.harness)
        _requirer_provide_ingress_requirements(
            harness=self.harness,
            relation=relation,
            host="10.1.10.1",
            port=9000,
        )

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

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_show_proxied_endpoints_action_no_relations(self, mock_get_loadbalancer_status):
        self.harness.begin_with_initial_hooks()
        action_event = Mock(spec=ActionEvent)
        self.harness.update_config({"external_hostname": "foo"})
        self.harness.charm._on_show_proxied_endpoints(action_event)
        action_event.set_results.assert_called_once_with(
            {"proxied-endpoints": '{"traefik-k8s": {"url": "http://foo"}}'}
        )

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_show_proxied_endpoints_action_only_ingress_per_app_relations(
        self, mock_get_loadbalancer_status
    ):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness, per_app_relation=True)
        _requirer_provide_ingress_requirements(
            harness=self.harness,
            relation=relation,
            host="10.0.0.1",
            ip="10.0.0.1",
            port=3000,
            per_app_relation=True,
        )

        self.harness.container_pebble_ready("traefik")

        action_event = Mock(spec=ActionEvent)
        self.harness.charm._on_show_proxied_endpoints(action_event)
        action_event.set_results.assert_called_once_with(
            {
                "proxied-endpoints": json.dumps(
                    {
                        "traefik-k8s": {"url": "http://testhostname"},
                        "remote": {"url": "http://testhostname/test-model-remote-0"},
                    }
                )
            }
        )

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_show_proxied_endpoints_action_only_ingress_per_unit_relations(
        self, mock_get_loadbalancer_status
    ):
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
                    {
                        "traefik-k8s": {"url": "http://testhostname"},
                        "remote/0": {"url": "http://testhostname/test-model-remote-0"},
                    }
                )
            }
        )

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_base_static_config(self, mock_get_loadbalancer_status):
        """Verify that the static config that should always be there, is in fact there."""
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})

        self.harness.begin_with_initial_hooks()

        # normally the charm would be reinitialized before receiving pebble-ready, but it isn't.
        # So we have to pretend to reset traefik's tcp_entrypoints that were passed in init
        charm = self.harness.charm
        charm.traefik._tcp_entrypoints = charm._tcp_entrypoints()

        self.harness.container_pebble_ready("traefik")
        static_config = charm.unit.get_container("traefik").pull(STATIC_CONFIG_PATH).read()
        cfg = yaml.safe_load(static_config)
        assert cfg["log"] == {"level": "DEBUG"}
        assert cfg["entryPoints"]["diagnostics"]["address"]
        assert cfg["entryPoints"]["web"]["address"]
        assert cfg["entryPoints"]["websecure"]["address"]
        assert cfg["ping"]["entryPoint"] == "diagnostics"
        assert cfg["providers"]["file"]["directory"]
        assert cfg["providers"]["file"]["watch"] is True

    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value=None,
    )
    def test_tcp_config(self, mock_get_loadbalancer_status):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        relation = relate(self.harness)
        data = _requirer_provide_ingress_requirements(
            harness=self.harness, relation=relation, host="10.0.0.1", port=3000, mode="tcp"
        )

        # normally the charm would be reinitialized before receiving pebble-ready, but it isn't.
        # So we have to pretend to reset traefik's tcp_entrypoints that were passed in init
        charm = self.harness.charm
        charm.traefik._tcp_entrypoints = charm._tcp_entrypoints()

        self.harness.container_pebble_ready("traefik")
        prefix = charm._get_prefix(data)
        assert charm._tcp_entrypoints() == {prefix: 3000}

        expected_entrypoint = {"address": ":3000"}
        static_config = charm.unit.get_container("traefik").pull(STATIC_CONFIG_PATH).read()
        assert yaml.safe_load(static_config)["entryPoints"][prefix] == expected_entrypoint

    def setup_forward_auth_relation(self) -> int:
        relation_id = self.harness.add_relation("experimental-forward-auth", "provider")
        self.harness.add_relation_unit(relation_id, "provider/0")
        self.harness.update_relation_data(
            relation_id,
            "provider",
            {
                "decisions_address": "https://oathkeeper.test-model.svc.cluster.local:4456/decisions",
                "app_names": '["charmed-app"]',
                "headers": '["X-User"]',
            },
        )

        return relation_id

    def test_forward_auth_relation_databag(self):
        self.harness.update_config({"enable_experimental_forward_auth": True})
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        provider_info = {
            "decisions_address": "https://oathkeeper.test-model.svc.cluster.local:4456/decisions",
            "app_names": ["charmed-app"],
            "headers": ["X-User"],
        }

        _ = self.setup_forward_auth_relation()

        self.assertTrue(self.harness.charm.forward_auth.is_ready())

        expected_provider_info = self.harness.charm.forward_auth.get_provider_info()

        assert expected_provider_info.decisions_address == provider_info["decisions_address"]
        assert expected_provider_info.app_names == provider_info["app_names"]
        assert expected_provider_info.headers == provider_info["headers"]

    def test_forward_auth_relation_changed(self):
        self.harness.update_config({"enable_experimental_forward_auth": True})
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        self.harness.charm._on_forward_auth_config_changed = mocked_handle = Mock(
            return_value=None
        )

        _ = self.setup_forward_auth_relation()
        assert mocked_handle.called

    def test_forward_auth_relation_removed(self):
        self.harness.set_leader(True)
        self.harness.update_config({"external_hostname": "testhostname"})
        self.harness.begin_with_initial_hooks()

        self.harness.charm._on_forward_auth_config_removed = mocked_handle = Mock(
            return_value=None
        )

        relation_id = self.setup_forward_auth_relation()
        self.harness.remove_relation(relation_id)

        assert mocked_handle.called


class TestTraefikCertTransferInterface(unittest.TestCase):
    def setUp(self):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        patcher = patch.object(TraefikIngressCharm, "version", property(lambda *_: "0.0.0"))
        self.mock_version = patcher.start()
        self.addCleanup(patcher.stop)
        self.container_name = "traefik"

    @patch("ops.model.Container.exec")
    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def test_transferred_ca_certs_are_updated(self, mock_get_loadbalancer_status, patch_exec):
        # Given container is ready, when receive-ca-cert relation joins,
        # then ca certs are updated.
        provider_app = "self-signed-certificates"
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()
        self.harness.set_can_connect(container=self.container_name, val=True)
        certificate_transfer_rel_id = self.harness.add_relation(
            relation_name="receive-ca-cert", remote_app=provider_app
        )
        self.harness.add_relation_unit(
            relation_id=certificate_transfer_rel_id, remote_unit_name=f"{provider_app}/0"
        )
        call_list = patch_exec.call_args_list
        assert [call.args[0] for call in call_list] == [
            ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"],
            ["update-ca-certificates", "--fresh"],
        ]

    @patch("ops.model.Container.exec")
    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def test_transferred_ca_certs_are_not_updated(self, mock_get_loadbalancer_status, patch_exec):
        # Given container is not ready, when receive-ca-cert relation joins,
        # then not attempting to update ca certs.
        provider_app = "self-signed-certificates"
        self.harness.set_leader(True)
        self.harness.set_can_connect(container=self.container_name, val=False)
        certificate_transfer_rel_id = self.harness.add_relation(
            relation_name="receive-ca-cert", remote_app=provider_app
        )
        self.harness.add_relation_unit(
            relation_id=certificate_transfer_rel_id, remote_unit_name=f"{provider_app}/0"
        )
        patch_exec.assert_not_called()


class TestConfigOptionsValidation(unittest.TestCase):
    @patch(
        "charm.TraefikIngressCharm._get_loadbalancer_status",
        new_callable=PropertyMock,
        return_value="10.0.0.1",
    )
    def setUp(self, mock_get_loadbalancer_status):
        self.harness: Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.harness.set_model_name("test-model")
        self.addCleanup(self.harness.cleanup)
        self.harness.handle_exec("traefik", ["update-ca-certificates", "--fresh"], result=0)
        self.harness.handle_exec(
            "traefik", ["find", "/opt/traefik/juju", "-name", "*.yaml", "-delete"], result=0
        )

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

    def test_when_external_hostname_not_set_use_ip_with_port_80(self):
        self.assertEqual(requirer.urls, {"remote/0": "http://10.0.0.1/test-model-remote-0"})

    def test_when_external_hostname_is_set_use_it_with_port_80(self):
        self.harness.update_config({"external_hostname": "testhostname"})
        self.assertEqual(requirer.urls, {"remote/0": "http://testhostname/test-model-remote-0"})

    def test_when_external_hostname_is_invalid_go_into_blocked_status(self):
        for invalid_hostname in [
            "testhostname:8080",
            "user:pass@testhostname",
            "testhostname/prefix",
        ]:
            with self.subTest(invalid_hostname=invalid_hostname):
                self.harness.update_config({"external_hostname": invalid_hostname})
                self.assertIsInstance(
                    self.harness.charm.unit.status, BlockedStatus, invalid_hostname
                )
                self.assertEqual(requirer.urls, {})

    def test_lb_annotations(self):
        test_cases = [
            ("key1=value1,key2=value2", {"key1": "value1", "key2": "value2"}),
            ("", {}),
            (
                "key1=value1,key_2=value2,key-3=value3,",
                {"key1": "value1", "key_2": "value2", "key-3": "value3"},
            ),
            (
                "key1=value1,key2=value2,key3=value3",
                {"key1": "value1", "key2": "value2", "key3": "value3"},
            ),
            ("example.com/key=value", {"example.com/key": "value"}),
            (
                "prefix1/key=value1,prefix2/another-key=value2",
                {"prefix1/key": "value1", "prefix2/another-key": "value2"},
            ),
            (
                "key=value,key.sub-key=value-with-hyphen",
                {"key": "value", "key.sub-key": "value-with-hyphen"},
            ),
            # Invalid cases
            ("key1=value1,key2=value2,key=value3,key4=", None),  # Missing value for key4
            (
                "kubernetes.io/description=this-is-valid,custom.io/key=value",
                None,
            ),  # Reserved prefix used
            ("key1=value1,key2", None),
            ("key1=value1,example..com/key2=value2", None),  # Invalid domain format (double dot)
            ("key1=value1,key=value2,key3=", None),  # Trailing equals for key3
            ("key1=value1,=value2", None),  # Missing key
            ("key1=value1,key=val=ue2", None),  # Extra equals in value
            ("a" * 256 + "=value", None),  # Key exceeds max length (256 characters)
            ("key@=value", None),  # Invalid character in key
            ("key. =value", None),  # Space in key
            ("key,value", None),  # Missing '=' delimiter
            ("kubernetes/description=", None),  # Key with no value
        ]

        for annotations, expected_result in test_cases:
            with self.subTest(annotations=annotations, expected_result=expected_result):
                # Update the config with the test annotation string
                self.harness.update_config({"loadbalancer_annotations": annotations})
                # Check if the _loadbalancer_annotations property returns the expected result
                self.assertEqual(self.harness.charm._loadbalancer_annotations, expected_result)
