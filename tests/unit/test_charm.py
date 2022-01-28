# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
#
# Learn more about testing at: https://juju.is/docs/sdk/testing

import unittest

from ops.testing import Harness

from charm import TraefikIngressCharm


class TestTraefikIngressCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(TraefikIngressCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_nothing(self):
        pass
