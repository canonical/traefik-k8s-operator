# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock, patch

from charm import SecretStore
from charm import TraefikIngressCharm

import os


# TODO: move to decorators
# TODO: don't mock uses_juju_secrets
class TestSecretStore(unittest.TestCase):
    def setUp(self):
        self.charm = Mock()
        # self.charm    : Harness[TraefikIngressCharm] = Harness(TraefikIngressCharm)
        self.secret_store = SecretStore(self.charm)
        self.dummy_private_key = "dummy_private_key"

    # def test_given_using_juju_secrets_when_store_private_key_then_add_secret_is_called(self):
    #     with patch.object(self.secret_store.__class__, "using_juju_secrets", return_value=True):
    #         content = {"private-key": self.dummy_private_key}

    #         self.secret_store.store_private_key(self.dummy_private_key)

    #         self.charm.app.add_secret.assert_called_with(
    #             content, label=self.secret_store._PRIVATE_KEY_SECRET_LABEL
    #         )
            
    #         # TODO: should we be able to get the secret back from the unit tests for this class?
    #         # expected_private_key = self.dummy_private_key
    #         # private_key = self.charm.model.get_secret(label=self.secret_store._PRIVATE_KEY_SECRET_LABEL).get_content()[
    #         #     "private-key"
    #         # ]
    #         # self.assertEqual(expected_private_key, private_key)
            

    # def test_given_not_using_juju_secrets_when_store_private_key_then_private_key_stored_in_stored_state(
    #     self,
    # ):
    #     with patch.object(self.secret_store.__class__, "using_juju_secrets", return_value=False):
    #         self.secret_store.store_private_key(self.dummy_private_key)

    #         self.assertEqual(self.charm._stored.private_key, self.dummy_private_key)

    def test_given_using_juju_secrets_when_remove_private_key_then_remove_all_revisions_is_called(self):
        os.environ["JUJU_SECRETS"] = "3.0.3"
        
        secret_store = SecretStore(self.charm)
        
        print(secret_store.using_juju_secrets())

    # def test_given_juju_secrets_available_when_get_private_key_then_get_is_secret_called(self):
    #     with patch.object(self.secret_store.__class__, "using_juju_secrets", return_value=True):
    #         secret = Mock()
    #         secret.get_content.return_value = {"private-key": self.dummy_private_key}
    #         self.charm.model.get_secret.return_value = secret

    #         private_key = self.secret_store.private_key

    #         self.charm.model.get_secret.assert_called_with(
    #             label=self.secret_store._PRIVATE_KEY_SECRET_LABEL
    #         )
    #         self.assertEqual(private_key, self.dummy_private_key)

    # def test_given_juju_secrets_not_available_when_get_private_key_then_private_key_returned_from_stored_state(
    #     self,
    # ):
    #     with patch.object(self.secret_store.__class__, "using_juju_secrets", return_value=False):
    #         self.charm._stored.private_key = self.dummy_private_key

    #         private_key = self.secret_store.private_key

    #         self.assertEqual(private_key, self.dummy_private_key)


if __name__ == "__main__":
    unittest.main()
