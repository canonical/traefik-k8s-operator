from unittest.mock import patch

import pytest

from charm import TraefikIngressCharm


@pytest.fixture
def traefik_charm():
    with patch("charm.KubernetesServicePatch"):
        with patch("lightkube.core.client.GenericSyncClient"):
            yield TraefikIngressCharm
