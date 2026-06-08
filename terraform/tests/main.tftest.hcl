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

run "expose_unset_by_default" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273
  }

  assert {
    condition     = length(juju_application.traefik.expose) == 0
    error_message = "expose block should not be created when the expose variable is unset"
  }
}

run "expose_set" {
  command = plan

  variables {
    model_uuid = run.setup_tests.model_uuid
    channel    = "latest/edge"
    # renovate: depName="traefik-k8s"
    revision = 273

    expose = {
      cidrs = "10.0.0.0/24"
    }
  }

  assert {
    condition     = length(juju_application.traefik.expose) == 1
    error_message = "expose block should be created when the expose variable is set"
  }
}
