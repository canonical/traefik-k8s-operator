# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest import mock
from unittest.mock import Mock, mock_open, patch

from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from lightkube import ApiError
from lightkube.models.core_v1 import ServicePort, ServiceSpec
from lightkube.models.meta_v1 import ObjectMeta
from lightkube.resources.core_v1 import Service
from lightkube.types import PatchType
from ops.charm import CharmBase
from ops.testing import Harness

CL_PATH = "charms.observability_libs.v0.kubernetes_service_patch.KubernetesServicePatch"
MOD_PATH = "charms.observability_libs.v0.kubernetes_service_patch"


class _FakeResponse:
    """Used to fake an httpx response during testing only."""

    def __init__(self, code):
        self.code = code

    def json(self):
        return {"apiVersion": 1, "code": self.code, "message": "broken"}


class _FakeApiError(ApiError):
    """Used to simulate an ApiError during testing."""

    def __init__(self, code):
        super().__init__(response=_FakeResponse(code))  # type: ignore[arg-type]


class _TestCharm(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.service_patch = KubernetesServicePatch(
            self, [("svc1", 1234, 1234), ("svc2", 1235, 1235)]
        )


class _TestCharmCustomServiceName(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.custom_service_name_service_patch = KubernetesServicePatch(
            self, [("svc1", 1234, 1234), ("svc2", 1235, 1235)], service_name="custom-service-name"
        )


class _TestCharmLBService(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.lb_service_patch = KubernetesServicePatch(
            self,
            [("test_lb_service", 4321, 4321, 7654), ("test_lb_service2", 1029, 1029, 3847)],
            service_type="LoadBalancer",
        )


class _TestCharmCustomLBServiceName(CharmBase):
    def __init__(self, *args):
        super().__init__(*args)
        self.custom_lb_service_name_service_patch = KubernetesServicePatch(
            self,
            [("test_lb_service", 4321, 4321, 7654), ("test_lb_service2", 1029, 1029, 3847)],
            service_name="custom-lb-service-name",
            service_type="LoadBalancer",
        )


class TestK8sServicePatch(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = Harness(_TestCharm, meta="name: test-charm")
        self.custom_service_name_harness = Harness(
            _TestCharmCustomServiceName, meta="name: test-charm"
        )
        self.lb_harness = Harness(_TestCharmLBService, meta="name: lb-test-charm")
        self.custom_lb_service_name_harness = Harness(
            _TestCharmCustomLBServiceName, meta="name: test-charm"
        )
        # Mock out calls to KubernetesServicePatch._namespace
        with mock.patch(f"{CL_PATH}._namespace", "test"):
            self.harness.begin()
            self.custom_service_name_harness.begin()
            self.lb_harness.begin()
            self.custom_lb_service_name_harness.begin()

    @patch(f"{CL_PATH}._namespace", "test")
    def test_k8s_service(self):
        service_patch = self.harness.charm.service_patch
        self.assertEqual(service_patch.charm, self.harness.charm)

        expected_service = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="test-charm",
                labels={"app.kubernetes.io/name": "test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "test-charm"},
                ports=[
                    ServicePort(name="svc1", port=1234, targetPort=1234),
                    ServicePort(name="svc2", port=1235, targetPort=1235),
                ],
                type="ClusterIP",
            ),
        )

        self.assertEqual(service_patch.service, expected_service)

    @patch(f"{CL_PATH}._namespace", "test")
    def test_k8s_service_with_custom_name(self):
        service_patch = self.custom_service_name_harness.charm.custom_service_name_service_patch
        self.assertEqual(service_patch.charm, self.custom_service_name_harness.charm)

        expected_service = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="custom-service-name",
                labels={"app.kubernetes.io/name": "custom-service-name"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "custom-service-name"},
                ports=[
                    ServicePort(name="svc1", port=1234, targetPort=1234),
                    ServicePort(name="svc2", port=1235, targetPort=1235),
                ],
                type="ClusterIP",
            ),
        )

        self.assertEqual(service_patch.service, expected_service)

    @patch(f"{CL_PATH}._namespace", "test")
    def test_k8s_load_balancer_service(self):
        service_patch = self.lb_harness.charm.lb_service_patch
        self.assertEqual(service_patch.charm, self.lb_harness.charm)

        expected_service = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="lb-test-charm",
                labels={"app.kubernetes.io/name": "lb-test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "lb-test-charm"},
                ports=[
                    ServicePort(name="test_lb_service", port=4321, targetPort=4321, nodePort=7654),
                    ServicePort(
                        name="test_lb_service2", port=1029, targetPort=1029, nodePort=3847
                    ),
                ],
                type="LoadBalancer",
            ),
        )

        self.assertEqual(service_patch.service, expected_service)

    @patch(f"{CL_PATH}._namespace", "test")
    def test_k8s_load_balancer_service_with_custom_name(self):
        service_patch = (
            self.custom_lb_service_name_harness.charm.custom_lb_service_name_service_patch
        )
        self.assertEqual(service_patch.charm, self.custom_lb_service_name_harness.charm)

        expected_service = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="custom-lb-service-name",
                labels={"app.kubernetes.io/name": "custom-lb-service-name"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "custom-lb-service-name"},
                ports=[
                    ServicePort(name="test_lb_service", port=4321, targetPort=4321, nodePort=7654),
                    ServicePort(
                        name="test_lb_service2", port=1029, targetPort=1029, nodePort=3847
                    ),
                ],
                type="LoadBalancer",
            ),
        )

        self.assertEqual(service_patch.service, expected_service)

    @patch(f"{CL_PATH}._namespace", "test")
    def test_optional_target_port_spec(self):
        service_patch = self.harness.charm.service_patch

        ports = [("test-app", 8080)]
        actual = service_patch._service_object(ports)
        expected = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="test-charm",
                labels={"app.kubernetes.io/name": "test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "test-charm"},
                ports=[ServicePort(name="test-app", port=8080, targetPort=8080)],
                type="ClusterIP",
            ),
        )
        self.assertEqual(actual, expected)

        ports = [("test-app", 8080, 9090)]
        actual = service_patch._service_object(ports)
        expected = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="test-charm",
                labels={"app.kubernetes.io/name": "test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "test-charm"},
                ports=[ServicePort(name="test-app", port=8080, targetPort=9090)],
                type="ClusterIP",
            ),
        )
        self.assertEqual(actual, expected)

    def test_event_listener_attach(self):
        charm = self.harness.charm
        with mock.patch(f"{CL_PATH}._patch") as patch:
            # Emit the install event, patch should be called
            charm.on.install.emit()
            self.assertEqual(patch.call_count, 1)
            # The patch should also be applied during upgrade_charm
            charm.on.upgrade_charm.emit()
            self.assertEqual(patch.call_count, 2)

    @patch(f"{MOD_PATH}.Client.patch")
    @patch(f"{MOD_PATH}.ApiError", _FakeApiError)
    @patch("lightkube.core.client.GenericSyncClient", Mock)
    def test_patch_k8s_service(self, client_patch):
        charm = self.harness.charm
        self.harness.set_leader(False)
        charm.on.install.emit()
        # Patch shouldn't work on a non-leader unit
        self.assertEqual(client_patch.call_count, 0)

        self.harness.set_leader(True)
        charm.on.install.emit()
        # Check we call the patch method on the client with the correct arguments
        client_patch.assert_called_with(
            Service, "test-charm", charm.service_patch.service, patch_type=PatchType.MERGE
        )

        client_patch.side_effect = _FakeApiError(403)
        with self.assertLogs(MOD_PATH) as logs:
            self.harness.charm.service_patch._patch(None)
            msg = "Kubernetes service patch failed: `juju trust` this application."
            self.assertIn(msg, ";".join(logs.output))

        client_patch.reset()
        client_patch.side_effect = _FakeApiError(500)

        with self.assertLogs(MOD_PATH) as logs:
            self.harness.charm.service_patch._patch(None)
            self.assertIn("Kubernetes service patch failed: broken", ";".join(logs.output))

    @patch(f"{MOD_PATH}.Client.get")
    @patch(f"{CL_PATH}._namespace", "test")
    @patch("lightkube.core.client.GenericSyncClient", Mock)
    def test_is_patched(self, get_patch):
        charm = self.harness.charm
        get_patch.return_value = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="test-charm",
                labels={"app.kubernetes.io/name": "test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "test-charm"},
                ports=[ServicePort(name="placeholder", port=65535)],
                type="ClusterIP",
            ),
        )

        self.assertEqual(charm.service_patch.is_patched(), False)

        get_patch.return_value = Service(
            apiVersion="v1",
            kind="Service",
            metadata=ObjectMeta(
                namespace="test",
                name="test-charm",
                labels={"app.kubernetes.io/name": "test-charm"},
            ),
            spec=ServiceSpec(
                selector={"app.kubernetes.io/name": "test-charm"},
                ports=[
                    ServicePort(name="svc1", port=1234, targetPort=1234),
                    ServicePort(name="svc2", port=1235, targetPort=1235),
                ],
                type="ClusterIP",
            ),
        )

        charm.on.install.emit()
        self.assertEqual(charm.service_patch.is_patched(), True)

    @patch("builtins.open", new_callable=mock_open, read_data="test")
    def test_patch_properties(self, mock):
        self.assertEqual(self.harness.charm.service_patch._app, "test-charm")
        self.assertEqual(self.harness.charm.service_patch._namespace, "test")
        mock.assert_called_with("/var/run/secrets/kubernetes.io/serviceaccount/namespace", "r")
