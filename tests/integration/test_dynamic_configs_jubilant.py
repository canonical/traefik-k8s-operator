#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration test: verify dynamic config files are written to the workload container.

Deploys traefik with 2+ apps integrated via ingress, then checks that the expected
dynamic config YAML files exist in /opt/traefik/juju/ inside the traefik container.
"""

import logging
import os
from pathlib import Path

import jubilant
import pytest
import yaml

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
TRAEFIK_RESOURCES = {
    name: val["upstream-source"] for name, val in METADATA["resources"].items()
}

TRAEFIK_APP_NAME = "traefik"
ALERTMANAGER_APP_NAME = "alertmanager"
CATALOGUE_APP_NAME = "catalogue"
DYNAMIC_CONFIG_DIR = "/opt/traefik/juju"


@pytest.fixture(scope="module")
def traefik_charm():
    charm_path = os.environ.get("CHARM_PATH")
    if charm_path:
        return Path(charm_path)
    charms = sorted(Path(".").glob("traefik*.charm"))
    if charms:
        return charms[0]
    raise FileNotFoundError(
        "Set CHARM_PATH to the built traefik charm, "
        "or place a traefik*.charm file in the repo root."
    )


def _all_settled(status: jubilant.Status) -> bool:
    """Return True when all apps are active and all agents are idle."""
    return jubilant.all_active(status) and jubilant.all_agents_idle(status)


@pytest.fixture(scope="module")
def deploy_traefik(juju, traefik_charm):
    """Deploy traefik."""
    juju.deploy(
        traefik_charm,
        TRAEFIK_APP_NAME,
        resources=TRAEFIK_RESOURCES,
        trust=True,
    )
    juju.config(TRAEFIK_APP_NAME, {"external_hostname": "traefik.test"})
    juju.wait(_all_settled, timeout=600)
    return TRAEFIK_APP_NAME


@pytest.fixture(scope="module")
def deploy_alertmanager(juju, deploy_traefik):
    """Deploy alertmanager and integrate with traefik."""
    juju.deploy(
        "ch:alertmanager-k8s",
        ALERTMANAGER_APP_NAME,
        channel="2/edge",
        trust=True,
    )
    juju.wait(_all_settled, timeout=600)
    juju.integrate(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(_all_settled, timeout=600)
    return ALERTMANAGER_APP_NAME


@pytest.fixture(scope="module")
def deploy_catalogue(juju, deploy_traefik):
    """Deploy catalogue and integrate with traefik."""
    juju.deploy(
        "ch:catalogue-k8s",
        CATALOGUE_APP_NAME,
        channel="1/edge",
        trust=True,
    )
    juju.wait(_all_settled, timeout=600)
    juju.integrate(f"{CATALOGUE_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    juju.wait(_all_settled, timeout=600)
    return CATALOGUE_APP_NAME


def _list_dynamic_configs(juju):
    """List YAML files in the dynamic config directory."""
    output = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        f"ls {DYNAMIC_CONFIG_DIR}/",
        container="traefik",
    )
    return [f for f in output.strip().split("\n") if f.endswith(".yaml")]


def test_dynamic_configs_present(juju, deploy_traefik, deploy_alertmanager, deploy_catalogue):
    """After integrating 2 apps, verify dynamic config files exist in the container."""
    files = _list_dynamic_configs(juju)
    logger.info("Dynamic config files in container: %s", files)

    # Each integrated app should have a config file matching juju_ingress_ingress_*_{app}.yaml
    alertmanager_configs = [f for f in files if ALERTMANAGER_APP_NAME in f]
    catalogue_configs = [f for f in files if CATALOGUE_APP_NAME in f]

    assert len(alertmanager_configs) == 1, (
        f"Expected exactly 1 config for {ALERTMANAGER_APP_NAME}, "
        f"found {alertmanager_configs} in {files}"
    )
    assert len(catalogue_configs) == 1, (
        f"Expected exactly 1 config for {CATALOGUE_APP_NAME}, "
        f"found {catalogue_configs} in {files}"
    )

    # Verify naming convention: juju_ingress_{relation_name}_{relation_id}_{app_name}.yaml
    for f in alertmanager_configs + catalogue_configs:
        assert f.startswith("juju_ingress_ingress_"), (
            f"Config file {f} doesn't follow expected naming convention"
        )


def test_dynamic_config_content_valid(juju, deploy_traefik, deploy_alertmanager, deploy_catalogue):
    """Verify that the dynamic config files contain valid traefik routing config."""
    files = _list_dynamic_configs(juju)

    for app_name in (ALERTMANAGER_APP_NAME, CATALOGUE_APP_NAME):
        config_file = next(f for f in files if app_name in f)
        output = juju.ssh(
            f"{TRAEFIK_APP_NAME}/0",
            f"cat {DYNAMIC_CONFIG_DIR}/{config_file}",
            container="traefik",
        )
        config = yaml.safe_load(output)
        logger.info("Config for %s: %s", app_name, config)

        # Every dynamic config should have http.routers and http.services
        assert "http" in config, f"No 'http' key in config for {app_name}"
        http = config["http"]
        assert "routers" in http, f"No routers in config for {app_name}"
        assert "services" in http, f"No services in config for {app_name}"

        # There should be at least one router and one service
        assert len(http["routers"]) >= 1, f"No routers defined for {app_name}"
        assert len(http["services"]) >= 1, f"No services defined for {app_name}"


def test_staging_artifacts_cleaned_up(juju, deploy_traefik, deploy_alertmanager, deploy_catalogue):
    """Verify that the tar archive and staging directory are removed after flush."""
    # The tar archive should not exist in the dynamic config dir
    output = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        f"ls {DYNAMIC_CONFIG_DIR}/ | grep '_ingress_configs.tar.gz' || true",
        container="traefik",
    )
    assert "_ingress_configs.tar.gz" not in output, (
        f"Tar archive was not cleaned up: {output.strip()}"
    )

    # The staging directory should not exist
    output = juju.ssh(
        f"{TRAEFIK_APP_NAME}/0",
        "test -d /tmp/_juju_ingress_staging && echo EXISTS || echo GONE",
        container="traefik",
    )
    assert "GONE" in output, "Staging directory /tmp/_juju_ingress_staging was not cleaned up"


def test_dynamic_config_removed_after_relation_removed(
    juju, deploy_traefik, deploy_alertmanager, deploy_catalogue
):
    """After removing a relation, the corresponding config file should be cleaned up."""
    # Verify file exists before removal
    files_before = _list_dynamic_configs(juju)
    alertmanager_configs = [f for f in files_before if ALERTMANAGER_APP_NAME in f]
    assert len(alertmanager_configs) == 1

    # Remove the alertmanager relation
    juju.remove_relation(f"{ALERTMANAGER_APP_NAME}:ingress", TRAEFIK_APP_NAME)
    # Wait until:
    # 1. traefik and catalogue are active
    # 2. all agents are idle (hooks have finished)
    # 3. the alertmanager↔traefik ingress relation is gone from juju status
    #
    # Condition (3) is key: immediately after remove_relation, all agents can
    # appear idle before Juju dispatches the relation-broken hooks. Waiting for
    # the relation to actually disappear from the status ensures traefik has run
    # its ingress-relation-broken hook and deleted the config file.
    juju.wait(
        lambda status: (
            jubilant.all_active(status, TRAEFIK_APP_NAME, CATALOGUE_APP_NAME)
            and jubilant.all_agents_idle(status)
            and not any(
                r.related_app == TRAEFIK_APP_NAME
                for r in status.apps[ALERTMANAGER_APP_NAME].relations.get("ingress", [])
            )
        ),
        timeout=300,
    )

    # Verify the alertmanager config file is gone
    files_after = _list_dynamic_configs(juju)
    alertmanager_configs_after = [f for f in files_after if ALERTMANAGER_APP_NAME in f]
    assert len(alertmanager_configs_after) == 0, (
        f"Expected alertmanager config to be removed after relation broken, "
        f"but found: {alertmanager_configs_after}"
    )

    # Catalogue config should still be present
    catalogue_configs_after = [f for f in files_after if CATALOGUE_APP_NAME in f]
    assert len(catalogue_configs_after) == 1, (
        f"Catalogue config should still exist, but found: {catalogue_configs_after}"
    )
