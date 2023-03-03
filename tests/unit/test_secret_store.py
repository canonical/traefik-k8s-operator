# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import MagicMock, Mock, PropertyMock, patch

from ops.model import Secret

from charm import SecretStore, TraefikIngressCharm

logging.basicConfig(level=logging.DEBUG)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


class MockModel:
    def __init__(self) -> None:
        self.framework = MagicMock()

    def get_secret(self, label):
        backend = self.framework.model._backend
        return Secret(backend=backend, label="sample_label")


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        self.charm = MagicMock(spec=TraefikIngressCharm)
        self.secret_store = SecretStore(self.charm)
        self.sample_private_key = "sample_private_key"

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_using_juju_secrets_is_called_then_returns_true(
        self, patch_from_environ
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True

        using_juju_secrets = self.secret_store.using_juju_secrets

        self.assertEqual(using_juju_secrets, True)

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_using_juju_secrets_is_called_then_returns_false(
        self, patch_from_environ
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False

        using_juju_secrets = self.secret_store.using_juju_secrets

        self.assertEqual(using_juju_secrets, False)

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_store_private_key_then_secret_is_added(
        self, patch_from_environ
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        content = {"private-key": self.sample_private_key}

        self.secret_store.store_private_key(self.sample_private_key)

        self.charm.app.add_secret.assert_called_with(content, label="PRIVATE_KEY")

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_store_private_key_then_private_key_stored_in_stored_state(
        self, patch_from_environ
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False

        self.secret_store.store_private_key(self.sample_private_key)

        private_key = self.charm._stored.private_key
        expected_private_key = self.sample_private_key
        self.assertEqual(private_key, expected_private_key)

    @patch("charm.SecretStore._PRIVATE_KEY_SECRET_LABEL", new_callable=PropertyMock)
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_get_private_key_then_private_key_is_retrieved_from_juju_secrets(
        self, patch_from_environ, patch_private_key_secret_label
    ):
        test_label = "TEST_PRIVATE_KEY"
        patch_private_key_secret_label.return_value = test_label
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        content = {"private-key": self.sample_private_key}
        self.charm.model.get_secret.return_value = Secret(
            backend=Mock(), label=test_label, content=content
        )

        private_key = self.secret_store.private_key

        self.charm.model.get_secret.assert_called_with(label=test_label)
        self.assertEqual(private_key, self.sample_private_key)

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_get_private_key_then_private_key_is_retrieved_from_stored_state(
        self, patch_from_environ
    ):
        secret_store = SecretStore(self.charm)
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False
        self.charm._stored.private_key = self.sample_private_key

        private_key = secret_store.private_key

        expected_private_key = self.sample_private_key
        self.assertEqual(private_key, expected_private_key)

    @patch("ops.model.Secret.remove_all_revisions")
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_remove_private_key_then_private_key_is_removed_from_juju_secrets(
        self, patch_from_environ, patched_remove_all_revisions
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        self.charm.model = MockModel()

        self.secret_store.remove_private_key()

        patched_remove_all_revisions.assert_called_once()

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_remove_private_key_then_private_key_is_removed_from_stored_state(
        self, patch_from_environ
    ):
        secret_store = SecretStore(self.charm)
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False
        self.charm._stored.private_key = self.sample_private_key

        secret_store.remove_private_key()

        self.assertEqual(self.charm._stored.private_key, None)

    @patch("charm.SecretStore.store_private_key")
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_migrate_private_key_then_key_is_not_migrated(
        self, patch_from_environ, patch_store_private_key
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False
        self.charm._stored.private_key = self.sample_private_key

        self.secret_store.migrate_private_key()

        patch_store_private_key.assert_not_called()
        self.assertEquals(self.charm._stored.private_key, self.sample_private_key)

    @patch("charm.SecretStore.store_private_key")
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_migrate_private_key_then_key_is_migrated(
        self, patch_from_environ, patch_store_private_key
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        self.charm._stored.private_key = self.sample_private_key

        self.secret_store.migrate_private_key()

        patch_store_private_key.assert_called_once()
        self.assertEquals(self.charm._stored.private_key, None)

    @patch("charm.SecretStore.store_private_key")
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_and_no_private_key_in_stored_state_when_migrate_private_key_then_key_is_not_migrated(
        self, patch_from_environ, patch_store_private_key
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        self.charm._stored.private_key = None

        self.secret_store.migrate_private_key()

        patch_store_private_key.assert_not_called()
        self.assertEquals(self.charm._stored.private_key, None)
