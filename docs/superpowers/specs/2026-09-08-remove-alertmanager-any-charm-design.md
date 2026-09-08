# Remove Alertmanager from Integration Tests Design

## Goal

Preserve the existing integration-test scenarios while replacing every deployment of the flaky
`alertmanager-k8s` charm with the repository's lightweight `any-charm-k8s` HTTP ingress tester.

## Approach

Reuse `health_src_overwrite()` from `tests/integration/any_charm_helpers.py`. It packages the
current ingress-per-app library and a Pebble-managed HTTP server, so routing assertions continue to
exercise a real backend. Deploy one shared application named `ingress` through an `ingress_app`
fixture and relate its `require-ingress` endpoint to Traefik's `ingress` endpoint.

Replace Alertmanager-specific constants, helper names, fixture parameters, local variables, and
test descriptions with generic ingress-tester terminology. Standalone TLS and Pebble-restart tests
will use the same deployment configuration directly so no integration module retains an
Alertmanager dependency.

## Behavior Preserved

- Ingress-per-app relation creation and removal.
- Dynamic Traefik configuration creation, validation, and cleanup.
- HTTP and HTTPS requests through every Traefik unit.
- Certificate-provider relation changes and Pebble restarts.
- Upgrade and leadership-change verification.
- Existing relation paths and proxied URL stability assertions.

The any-charm requirer endpoint is `require-ingress`; Traefik's provider endpoint remains
`ingress`. Dynamic configuration filenames continue to use the provider relation name.

## Validation

Add focused tests for the shared fixture's deployment contract and generic endpoint lookup where
practical. Run targeted tests first, then formatting, lint/static checks, unit tests, and integration
test collection. Run live integration tests only when a suitable Juju Kubernetes model is available.
A repository search must confirm that tracked integration-test Python files contain no Alertmanager
deployment or naming references.

## Documentation

Add the required release-note artifact and changelog entry describing the integration-test
dependency replacement.