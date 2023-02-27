# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import MagicMock, Mock, patch

from charm import SecretStore, TraefikIngressCharm

from ops.model import Secret

logging.basicConfig(level=logging.DEBUG)
logging.getLogger().setLevel(logging.DEBUG)
logger = logging.getLogger(__name__)


class MockCharm():
    def __init__(self) -> None:
        self.model = MockModel()


class MockModel:
    def __init__(self) -> None:
        self.framework = MagicMock()
    
    def get_secret(self, label):
        backend = self.framework.model._backend
        return Secret(backend=backend, label = "dummy_label")


class MockSecret:
    def remove_all_revisions(self):
        return MagicMock()


class TestSecretStore(unittest.TestCase):
    def setUp(self):
        # TODO: do I need to re-create the instance of the charm for each test?
        self.charm = MagicMock(spec=TraefikIngressCharm)
        self.secret_store = SecretStore(self.charm)
        self.dummy_private_key = "dummy_private_key"

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
        content = {"private-key": self.dummy_private_key}

        self.secret_store.store_private_key(self.dummy_private_key)
        
        self.charm.app.add_secret.assert_called_with(content, label="PRIVATE_KEY")

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_store_private_key_then_private_key_stored_in_stored_state(
        self, patch_from_environ
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False

        self.secret_store.store_private_key(self.dummy_private_key)

        private_key = self.charm._stored.private_key
        expected_private_key = self.dummy_private_key
        self.assertEqual(private_key, expected_private_key)

    # # TODO
    # @patch("ops.model.get_secret")
    # @patch("charm.JujuVersion.from_environ")
    # def test_given_juju_has_secrets_when_get_private_key_then_private_key_is_retrieved_from_juju_secrets(
    #     self, patch_from_environ, patch_get_secret
    # ):
    #     secret_store = SecretStore(self.charm)
    #     patch_juju_version = Mock()
    #     patch_from_environ.return_value = patch_juju_version
    #     patch_juju_version.has_secrets = True
    #     self.charm.app.get_secret.return_value = {"private-key": self.dummy_private_key}

    #     private_key = secret_store.private_key

    #     logger.warning("########################## testing log ############################")
    #     logger.warning(self.charm.app.get_secret.call_args_list)
    #     patch_get_secret.assert_called_with(label="PRIVATE_KEY")
    #     self.assertEqual(private_key, self.dummy_private_key)

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_get_private_key_then_private_key_is_retrieved_from_stored_state(
        self, patch_from_environ
    ):
        secret_store = SecretStore(self.charm)
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False
        self.charm._stored.private_key = self.dummy_private_key

        private_key = secret_store.private_key

        expected_private_key = self.dummy_private_key
        self.assertEqual(private_key, expected_private_key)

    # TODO: How should I mock `self.charm.model.get_secret(label=self._PRIVATE_KEY_SECRET_LABEL).remove_all_revisions()`?
    @patch("ops.model.Secret")
    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_secrets_when_remove_private_key_then_private_key_is_removed_from_juju_secrets(
        self, patch_from_environ, patched_secret
    ):
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = True
        self.charm.model = MockModel()
        
        self.secret_store.remove_private_key()

        patched_secret.remove_all_revisions.assert_called_once()

    @patch("charm.JujuVersion.from_environ")
    def test_given_juju_has_no_secrets_when_remove_private_key_then_private_key_is_removed_from_stored_state(
        self, patch_from_environ
    ):
        secret_store = SecretStore(self.charm)
        patch_juju_version = Mock()
        patch_from_environ.return_value = patch_juju_version
        patch_juju_version.has_secrets = False
        self.charm._stored.private_key = self.dummy_private_key

        secret_store.remove_private_key()

        self.assertEqual(self.charm._stored.private_key, None)

    # TODO: Migration from stored state to juju secrets test.
