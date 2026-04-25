(changelog)=

# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

Each revision is versioned by the date of the revision.

## 2026-04-25

- Fixed a missing space in the Raw mode warning log message in the `traefik_route` charm library.

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
