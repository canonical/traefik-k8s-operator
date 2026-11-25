---
myst:
  html_meta:
    "description lang=en": "Upgrade the Traefik rock, test the dev image with the charm, and promote it through OCI Factory."
---

(how_to_upgrade_rock)=

# How to upgrade the Traefik rock

This guide is for maintainers updating the workload image used by the
Traefik charm.

## Repositories and images

- [`canonical/traefik-rock`](https://github.com/canonical/traefik-rock) contains
  the rock definitions, with one directory per upstream release.
- `ghcr.io/canonical/traefik:dev` is published from the rock pull request
  branch. Use it only for testing.
- [`canonical/oci-factory`](https://github.com/canonical/oci-factory) builds and
  publishes the official image to
  [`ubuntu/traefik` on Docker Hub](https://hub.docker.com/r/ubuntu/traefik)
  from a commit and directory in `traefik-rock`.
- [`canonical/traefik-k8s-operator`](https://github.com/canonical/traefik-k8s-operator)
  contains the charm, which uses the official image. A temporary pull request
  points its `traefik-image` resource at the dev image for integration testing.

## Create the version directory

Replace all angle-bracketed placeholders with your release values. Set the
versions without the `v` prefix:

```bash
OLD_VERSION='<previous-version>'
NEW_VERSION='<new-version>'
```

Clone the rock repository and create a branch for the new version:

```bash
gh repo clone canonical/traefik-rock
cd traefik-rock
git switch -c "rock/$NEW_VERSION"
```

Copy the previous version directory from the same supported release series into
`$NEW_VERSION`. Keep `$OLD_VERSION` unchanged:

```bash
cp -r "$OLD_VERSION" "$NEW_VERSION"
```

## Update the rock definition

Update the new directory's `rockcraft.yaml` to use your target upstream release:

- Set `version` to the release version without the `v` prefix.
- Set both `parts.traefik.source-tag` and
  `parts.traefik-frontend.source-tag` to the upstream Git tag, including its
  `v` prefix.
- Set `TRAEFIK_VERSION` in the `traefik` part's `build-environment` to the same
  upstream Git tag.
- Check the upstream `go.mod` and web UI build requirements. Update the Go and
  Node build snap channels if the target release requires different versions.

### Example rock definition

Replace the placeholders in this excerpt with your target release and its
required build snap versions. Preserve the rest of the copied `rockcraft.yaml`:

```yaml
name: traefik
version: "<new-version>"

parts:
  traefik-frontend:
    source-tag: "v<new-version>"
    build-snaps:
      - node/<node-version>/stable

  traefik:
    source-tag: "v<new-version>"
    build-snaps:
      - go/<go-version>/stable
    build-environment:
      - TRAEFIK_VERSION: "v<new-version>"
```

Compare the new directory with the previous one to confirm the intended
changes:

```bash
diff -ru "$OLD_VERSION" "$NEW_VERSION"
```

## Open and test the rock pull request

Commit the new directory and open a pull request against `main`:

```bash
git add "$NEW_VERSION"
git commit -m "chore: Add $NEW_VERSION"
git push -u origin "rock/$NEW_VERSION"
gh pr create --title "chore: Add $NEW_VERSION" --fill
```

The `Pull Requests` workflow packs and tests the rock on `amd64`, `arm64`, and
`s390x`, then runs the `goss` checks. Wait for the workflow to pass. See
[traefik-rock PR #106](https://github.com/canonical/traefik-rock/pull/106) for
an example.

Do not merge or close the pull request yet. The next step publishes a dev image
from this branch.

## Publish the dev image

In the GitHub UI, open **Actions** > `Publish rock to GHCR:dev` >
**Run workflow**. Leave **Use workflow from** set to `main`, and set the separate
**Branch to build from** input to the pull request branch, `rock/<new-version>`.
**Use workflow from** selects the workflow definition; **Branch to build from**
selects the rock sources. Then run the workflow.

The equivalent command is:

```bash
gh workflow run rock-release-dev.yaml --repo canonical/traefik-rock --ref main -f "branch=rock/$NEW_VERSION"
```

Run this before merging or closing the rock pull request: the workflow detects
version directories changed relative to `main` and publishes them to
`ghcr.io/canonical/traefik:dev`.

Wait for the workflow to finish, then confirm that the assemble-and-publish job
succeeded rather than being skipped. See the
[example dev publish run](https://github.com/canonical/traefik-rock/actions/runs/44269729342).

## Test the dev image with the charm

Open a temporary pull request in the charm repository that points the
`traefik-image` resource at the dev image. Run these commands from your workspace
directory, outside the rock repository:

```bash
gh repo clone canonical/traefik-k8s-operator
cd traefik-k8s-operator
git switch -c "test-traefik-$NEW_VERSION-dev"
```

In `metadata.yaml`, change only `resources.traefik-image.upstream-source` to
`ghcr.io/canonical/traefik:dev`. Commit the edit and open the test pull request:

```bash
git add metadata.yaml
git commit -m "test: use traefik dev rock for $NEW_VERSION"
git push -u origin "test-traefik-$NEW_VERSION-dev"
gh pr create --title "[DO NOT MERGE] test traefik-rock $NEW_VERSION" --fill
```

Mark the pull request as test-only and **do not merge it**. It leaves the charm
pointing at the dev image, which is not suitable for a release.

Wait for the full integration test matrix to pass. See
[traefik-k8s-operator PR #809](https://github.com/canonical/traefik-k8s-operator/pull/809)
for an example. If tests fail, fix the rock, publish a new dev image, and rerun
the integration tests.

## Merge the rock pull request

After the rock pull request workflow and the charm integration tests pass, merge
the rock pull request into `main`.

Return to the rock repository and record the merge commit SHA. OCI Factory uses
that commit to find the version directory. Use the merge commit shown on the
pull request, rather than a later unrelated commit on `main`:

```bash
git switch main
git pull
gh pr view '<rock-pr-number>' --json mergeCommit --jq '.mergeCommit.oid'
```

## Promote through OCI Factory

Open a pull request in `canonical/oci-factory` manually. From your workspace
directory, clone the repository and create a branch:

```bash
gh repo clone canonical/oci-factory
cd oci-factory
git switch -c "chore/add-traefik-$NEW_VERSION"
```

Update the existing entry in `oci/traefik/image.yaml` to use the merge commit
and new version directory. Keep the release track and risk used by the charm.
See [OCI Factory PR #1335](https://github.com/canonical/oci-factory/pull/1335/changes)
for an example:

```yaml
version: 2
upload:
  - source: canonical/traefik-rock
    commit: "<merge-commit-sha>"
    directory: "<new-version>"
    release:
      <release-track>:
        end-of-life: "<end-of-life-timestamp>"
        risks:
          - "<risk>"
```

Review these fields:

- Set `commit` and `directory` to the new rock commit and version directory.
- Keep the existing release track and risk unchanged. The release track does
  not include the image tag's risk suffix.
- Set `end-of-life` to no more than one year after the release date. Use the
  longest period that OCI Factory CI accepts, but never more than one year.
  Set the timestamp in UTC using `YYYY-MM-DDT00:00:00Z` format.
- Remove the previous `ignored-vulnerabilities` entries so the new image is
  scanned without inherited exceptions. Omit the field when no exceptions are
  needed.

If OCI Factory reports vulnerabilities that you cannot fix in this upgrade,
discuss the severity and impact with the team before adding them to
`ignored-vulnerabilities`. Add entries temporarily and include the CVE, package,
CVSS score, Ubuntu priority, status, and link. See
[OCI Factory PR #1177](https://github.com/canonical/oci-factory/pull/1177/changes)
for an example of adding entries to `ignored-vulnerabilities` in `image.yaml`.

Commit and push the change, then open the pull request:

```bash
git add oci/traefik/image.yaml
git commit -m "chore: Add traefik $NEW_VERSION"
git push -u origin "chore/add-traefik-$NEW_VERSION"
gh pr create --title "chore: Add traefik $NEW_VERSION" --fill
```

Check the OCI Factory integration tests and vulnerability scan results. Resolve
failures, or obtain team agreement for temporary exceptions as described
above, before merging.

## Finish the charm update

After the OCI Factory pull request merges and the image is published, close the
temporary charm test pull request without merging it. The next pull request in
`traefik-k8s-operator` will consume the new image.

## Related information

- [traefik-rock PR #106](https://github.com/canonical/traefik-rock/pull/106):
  add a new Traefik version directory.
- [Example dev image publish run](https://github.com/canonical/traefik-rock/actions/runs/44269729342):
  publish the dev image used for integration tests.
- [traefik-k8s-operator PR #809](https://github.com/canonical/traefik-k8s-operator/pull/809):
  test the dev image in the charm integration suite.
- [OCI Factory PR #1335](https://github.com/canonical/oci-factory/pull/1335/changes):
  promote the image and update its end of life and ignored vulnerabilities.
