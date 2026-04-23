# Contributing

![GitHub License](https://img.shields.io/github/license/canonical/traefik-k8s-operator)
![GitHub Commit Activity](https://img.shields.io/github/commit-activity/y/canonical/traefik-k8s-operator)
![GitHub Lines of Code](https://img.shields.io/tokei/lines/github/canonical/traefik-k8s-operator)
![GitHub Issues](https://img.shields.io/github/issues/canonical/traefik-k8s-operator)
![GitHub PRs](https://img.shields.io/github/issues-pr/canonical/traefik-k8s-operator)
![GitHub Contributors](https://img.shields.io/github/contributors/canonical/traefik-k8s-operator)
![GitHub Watchers](https://img.shields.io/github/watchers/canonical/traefik-k8s-operator?style=social)

This document explains the processes and practices recommended for contributing enhancements to the Traefik Operator.

## Overview

- Generally, before developing enhancements to this charm, you should consider [opening an issue
  ](https://github.com/canonical/traefik-k8s-operator/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach
  us at [Canonical Matrix public channel](https://matrix.to/#/#charmhub-charmdev:ubuntu.com)
  or [Discourse](https://discourse.charmhub.io/).
- Familiarizing yourself with the [Juju documentation](https://documentation.ubuntu.com/juju/3.6/howto/manage-charms/)
  will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines
  - code quality
  - test coverage
  - user experience for Juju operators of this charm.
- Once your pull request is approved, we squash and merge your pull request branch onto
  the `main` branch. This creates a linear Git commit history.
- For further information on contributing, please refer to our
  [Contributing Guide](https://github.com/canonical/platform-engineering-contributing-guide).

## Code of conduct

When contributing, you must abide by the
[Ubuntu Code of Conduct](https://ubuntu.com/community/ethos/code-of-conduct).

## Changelog

Please ensure that any new feature, fix, or significant change is documented by
adding an entry to the [CHANGELOG.md](docs/changelog.md) file. Use the date of the
contribution as the header for new entries.

To learn more about changelog best practices, visit [Keep a Changelog](https://keepachangelog.com/).

## Submissions

If you want to address an issue or a bug in this project,
notify in advance the people involved to avoid confusion;
also, reference the issue or bug number when you submit the changes.

- [Fork](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/working-with-forks/about-forks)
  our [GitHub repository](https://github.com/canonical/traefik-k8s-operator)
  and add the changes to your fork, properly structuring your commits,
  providing detailed commit messages and signing your commits.
- Make sure the updated project builds and runs without warnings or errors;
  this includes linting, documentation, code and tests.
- Submit the changes as a
  [pull request (PR)](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request-from-a-fork).

Your changes will be reviewed in due time; if approved, they will be eventually merged.

### Signing commits

To improve contribution tracking,
we use the [Canonical contributor license agreement](https://assets.ubuntu.com/v1/ff2478d1-Canonical-HA-CLA-ANY-I_v1.2.pdf)
(CLA) as a legal sign-off, and we require all commits to have verified signatures.

#### Canonical contributor agreement

Canonical welcomes contributions to the Traefik Operator. Please check out our
[contributor agreement](https://ubuntu.com/legal/contributors) if you're interested in contributing to the solution.

The CLA sign-off is simple line at the
end of the commit message certifying that you wrote it
or have the right to commit it as an open-source contribution.

#### Verified signatures on commits

All commits in a pull request must have cryptographic (verified) signatures.
To add signatures on your commits, follow the
[GitHub documentation](https://docs.github.com/en/authentication/managing-commit-signature-verification/signing-commits).

### Release notes

This repository uses an [automated workflow](https://github.com/canonical/traefik-k8s-operator/blob/main/.github/workflows/release_notes_automation.yaml)
for preparing and publishing release notes.
The workflow uses YAML artifacts summarizing project changes and releases
to generate the release notes corresponding to stable revisions of the charm.

When preparing your pull request, please add a change artifact following
[`_change-artifact-template.yaml`](https://github.com/canonical/traefik-k8s-operator/blob/main/docs/release-notes/template/_change-artifact-template.yaml)
that summarizes the feature, bug fix, or other change you're making to the project.

To enforce the creation of change artifacts, this project includes a
[compliance workflow](https://github.com/canonical/traefik-k8s-operator/blob/main/.github/workflows/check_release_notes_artifact.yaml)
that will run over your pull request and fail if no artifact exists.
If your pull request doesn't necessitate a change artifact, use the `no-release-note`
label on your pull request to opt out of the compliance workflow.

Change artifacts include a key, `pr`, to capture the URL(s) of the relevant
pull requests associated with the change.
You may leave this key empty while preparing your pull request; the compliance workflow
will automatically push a commit to your pull request to update this key
with the corresponding URL.

### AI

You are free to use any tools you want while preparing your contribution, including
AI, provided that you do so lawfully and ethically.

Avoid using AI to complete issues tagged with the "good first issues" label. The
purpose of these issues is to provide newcomers with opportunities to contribute
to our projects and gain coding skills. Using AI to complete these tasks
undermines their purpose.

We have created instructions and tools that you can provide AI while preparing your contribution: [`copilot-collections`](https://github.com/canonical/copilot-collections)

While it isn't necessary to use `copilot-collections` while preparing your
contribution, these files contain details about our quality standards and
practices that will help the AI avoid common pitfalls when interacting with
our projects. By using these tools, you can avoid longer review times and nitpicks.

If you choose to use AI, please disclose this information to us by indicating
AI usage in the PR description (for instance, marking the checklist item about
AI usage). You don't need to go into explicit details about how and where you used AI.

Avoid submitting contributions that you don't fully understand.
You are responsible for the entire contribution, including the AI-assisted portions.
You must be willing to engage in discussion and respond to any questions, comments,
or suggestions we may have. 

## Notable design decisions

Traefik is a cluster-less proxy: each unit is performing its own routing decisions and keeping track of the health of upstreams (i.e., the addresses it routes requests for).
Each Traefik operator listens to changes in the `ingress-per-unit` relations and generates their own configurations.
Only the leader unit of the Traefik operator, however, communicates "back" with the application on the other side of the relation by providing the URL at which the units are reachable.

**Limitation:** Since follower (i.e., "non-leader") units of a Juju application _cannot_ access their application databag in the relation (see [this Juju bug report](https://bugs.launchpad.net/juju/+bug/1911010)), it can be the case that follower units starts routing to units that have not yet been notified by the leader unit of the Traefik operator, what their externally-reachable URL is.

In order to configure Traefik, we use its [File provider](https://doc.traefik.io/traefik/providers/file/), which uses `inotify` mechanisms to know when new files are created or modified in the filesystem.
Unfortunately, `inotify` does not work in the [upstream Traefik image](https://hub.docker.com/_/traefik), which is why we resorted to:

* storing the unit configuration in a _mounted volume_
* run the Traefik process on a custom container image built on the [`ubuntu` base image](https://hub.docker.com/_/ubuntu), see the [Container image](#container-image) section.

## Develop

To make contributions to this charm, you'll need a working
[development setup](https://documentation.ubuntu.com/juju/latest/howto/manage-your-juju-deployment/set-up-your-juju-deployment-local-testing-and-development/).

The code for this charm can be downloaded as follows:

```
git clone https://github.com/canonical/traefik-k8s-operator
```

These instructions assume you will run the charm on [`microk8s`](https://microk8s.io), and relies on the `dns`, `storage`, `registry` and `metallb` plugins:

```sh
sudo snap install microk8s --classic
microk8s enable storage dns
microk8s enable metallb 192.168.0.10-192.168.0.100  # You will likely want to change these IP ranges
```

The `storage` and `dns` plugins are required machinery for most Juju charms running on K8s.
This charm is no different.
The `metallb` plugin is needed so that the Traefik ingress will receive on its service, which is of type `LoadBalancer`, an external IP it can propagate to the proxied applications.

The setup for Juju consists as follows:

```sh
sudo snap install juju --classic
juju bootstrap microk8s development
```

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Test

This project uses `tox` for managing test environments. There are some pre-configured environments
that can be used for linting and formatting code when you're preparing contributions to the charm:

* ``tox``: Executes all of the basic checks and tests (``lint`` and ``unit``).
* ``tox -e fmt``: Update your code according to linting rules.
* ``tox -e lint``: Runs a range of static code analysis to check the code.
* ``tox -e unit``: Runs the unit tests.
* ``tox -e integration``: Runs the integration tests.

### Build the charm

Build the charm in this git repository using:

```shell
charmcraft pack
```

### Container image

We are using an Ubuntu-based image built from [this repository](https://github.com/jnsgruk/traefik-oci-image).

The reason **not** to use the [upstream Traefik image](https://hub.docker.com/_/traefik), is that the [File provider](https://doc.traefik.io/traefik/providers/file/) the charm uses (see [Notable design decisions](#notable design-decisions) section) does not seem to work in the upstream, busybox-based Traefik image.

### Deploy

```sh
# Create a model
juju add-model dev
# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=docker.io/jnsgruk/traefik:2.6.1
```


