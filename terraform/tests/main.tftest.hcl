# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

run "setup_tests" {
  module {
    source = "./tests/setup"
  }
}

run "basic_deploy" {
  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273
  }

  assert {
    condition     = output.application.name == "traefik"
    error_message = "traefik app_name did not match expected"
  }
}

run "expose_false_by_default" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273
  }

  assert {
    condition     = length(juju_application.traefik.expose) == 0
    error_message = "expose block should not be created when expose is false"
  }
}

run "expose_true_without_hostname_errors" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273

    expose = true
  }

  expect_failures = [
    var.expose,
  ]
}

run "expose_true_with_hostname" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273

    expose = true
    config = {
      external_hostname = "traefik.test"
    }
  }

  assert {
    condition     = length(juju_application.traefik.expose) == 1
    error_message = "expose block should be created when expose is true and external_hostname is set"
  }

  assert {
    condition     = juju_application.traefik.config["juju-external-hostname"] == "traefik.test"
    error_message = "juju-external-hostname should be derived from external_hostname when exposing"
  }
}

run "expose_false_with_hostname" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273

    expose = false
    config = {
      external_hostname = "traefik.test"
    }
  }

  assert {
    condition     = length(juju_application.traefik.expose) == 0
    error_message = "expose block should not be created when expose is false, even with external_hostname set"
  }

  assert {
    condition     = lookup(juju_application.traefik.config, "juju-external-hostname", "") == ""
    error_message = "juju-external-hostname should not be derived when not exposing"
  }
}
