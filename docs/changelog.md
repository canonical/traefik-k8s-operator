(changelog)=

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each revision is versioned by the date of the revision.

## 2026-06-24

- Fixed Traefik entrypoint `readTimeout` defaults for HTTP and TCP traffic entrypoints so large uploads are not cut off after 60 seconds on Traefik v2.11.2+.
- Added integration tests for Traefik charm upgrade.

## 2026-06-19

- Removed "How to force HTTPS redirect" documentation as it is stale code. 

## 2026-06-18

- Migrated the RTD documentation URL under the Canonical domain.

## 2026-06-08

- Added an `expose` input to the Terraform module to make Traefik publicly available over the network.

## 2026-06-05

- Added support for `ubuntu@26.04` on the charm.

## 2026-06-04

- Updated Terraform module Juju provider version constraint to support Juju 4.

## 2026-06-03

- Added the charm architecture documentation page.

## 2026-06-01

- Updated ingress lib to publish new attribute `is_port_opened` on the requirer's side
  that represents whether the port requested is open or not.

## 2026-06-01

- Update the charm to use 2.11-26.04_edge tag of traefik image.

## 2026-05-28

- Push all dynamic configurations together in the end rather than individual pushes.
- Reduced unnecessary LoadBalancer reconciliations by removing redundant `_reconcile_lb()` calls from CA certificate and configuration paths, and removed per-relation maintenance status churn during ingress processing.

## 2026-05-22

- Fixed `delete_dynamic_configs` and `delete_dynamic_config` to guard against missing directory/file, preventing `ExecError` crash on first container start or after pod churn.

## 2026-05-19

- Added the `resources` variable to the Terraform charm module so users can pin images for Traefik.

## 2026-05-07

- Fixed `_on_remove` to only delete the LoadBalancer resource when the application is fully removed (0 planned units), preventing accidental LB deletion during scale-down.

## 2026-04-20

- Replaced `@property` with `@functools.cached_property` on frequently accessed charm attributes.

## 2025-05-07

- Fixed reading the CA certificates from the `certificate-transfer` relation.

## 2026-05-05

- Ensure hosts ordering in the dynamic configuration files.

## 2026-04-19

- Removed redundant `relation-created` and `relation-joined` event observers from the ingress v1 and v2 libraries; ingress processing now triggers only on `relation-changed`.

## 2026-03-30

- Added support for release notes.

## 2025-03-17

- Changed certificate mode from `UNIT` to `APP` mode.

## 2026-03-13

- Add support for UDP entrypoints in the `traefik-route` relation.

## 2026-03-16

- Add security documentation.

## 2025-03-12

- Updated charm code to trigger certificate refresh conditionally rather than through refresh hooks.

## 2025-02-26

- Add some more logs and unit tests on the `proxied_endpoints` method.

## 2026-01-29

- Removed leader requirement on `TraefikRouteRequirer` to update the stored state. 

## 2026-01-27

- Cleaned up the repository to remove stale comments, align `tox.ini` and remove `requirements.txt`.

## 2026-01-19

- Add how to upgrade documentation.

## 2026-01-08

- Migrated documentation to GitHub and set up RTD project.
- Added workflow to check for CLA compliance.

## 2025-11-28

### Changed

- Fixed Traefik accessing Pebble before container is ready.
