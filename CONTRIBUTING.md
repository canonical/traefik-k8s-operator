# Contributing

This documents explains the processes and practices recommended for contributing enhancements to this operator.

- Generally, before developing enhancements to this charm, you should consider [opening an issue](https://github.com/canonical/traefik-k8s-operator/issues) explaining your use case.
- If you would like to chat with us about your use-cases or proposed implementation, you can reach us at [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the [Charmed Operator Framework](https://juju.is/docs/sdk) library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review typically examines:
  - code quality
  - test coverage
  - user experience for Juju administrators this charm
- When evaluating design decisions, we optimize for the following personas, in descending order of priority:
  - the Juju administrator
  - charm authors that need to integrate with this charm through relations
  - the contributors to this charm's codebase
- Please help us out in ensuring easy to review branches by rebasing your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.

## Notable design decisions

Traefik is a cluster-less proxy: each unit is performing its own routing decisions and keeping track of the health of upstreams (i.e., the addresses it routes requests for).
Each Traefik operator listens to changes in the `ingress` relations and generates their own configurations.
Only the leader unit of the Traefik operator, however, communicates "back" with the application on the other side of the relation by providing the URL at which the units are reachable.

**Limitation:** Since follower (i.e., "non-leader") units of a Juju application _cannot_ access their application databag in the relation (see [this Juju bug report](https://bugs.launchpad.net/juju/+bug/1911010)), it can be the case that follower units starts routing to units that have not yet been notified by the leader unit of the Traefik operator, what their externally-reachable URL is.

In order to configure Traefik, we use its [File provider](https://doc.traefik.io/traefik/providers/file/), which uses `inotify` mechanisms to know when new files are created or modified in the filesystem.
Unfortunately, `inotify` does not work in most container filesystems, including the one of the [upstream Traefik image](https://hub.docker.com/_/traefik), which is why we resorted to:

* storing the unit configuration in a _mounted volume_
* run the Traefik process on a custom container image built on the [`ubuntu` base image](https://hub.docker.com/_/ubuntu).

## Developing

You can use the environments created by `tox` for development:

```shell
tox --notest -e unit
source .tox/unit/bin/activate
```

### Testing

```shell
tox -e fmt           # update your code according to linting rules
tox -e lint          # code style
tox -e unit          # unit tests
tox -e integration   # integration tests
tox                  # runs 'lint' and 'unit' environments
```

### Setup

These instructions assume you will run the charm on [`microk8s`](https://microk8s.io), and relies on the `dns`, `storage`, `registry` and `metallb` plugins:

```sh
sudo snap install microk8s --classic
microk8s enable storage dns registry
microk8s enable metallb 192.168.0.10-192.168.0.100  # You will likely want to change these IP ranges
```

The `storage`, `dns` and `registry` plugins are required machinery for most Juju charms running on K8s.
This charm is no different.
The `metallb` plugin is needed so that the Traefik ingress will receive on its service, which is of type `LoadBalancer`, an external IP it can propagate to the proxied applications.

The setup for Juju consists as follows:

```sh
sudo snap install juju --classic
juju bootstrap microk8s development
```

### Build

Build the charm in this git repository using:

```shell
charmcraft pack
```

The charm uses a custom container image built on Ubuntu:

```sh
docker build . -t localhost:32000/traefik:v1
docker push localhost:32000/traefik:v1  # This will push the locally-built image to the registry provided by microk8s
```

The reason **not** to use the [upstream Traefik image](https://hub.docker.com/_/traefik), is that the [File provider](https://doc.traefik.io/traefik/providers/file/) the charm uses (see [Notable design decisions](#notable design-decisions) section) does not seem to work in the upstream, busybox-based Traefik image.

### Deploy

```sh
# Create a model
juju add-model dev
# Enable DEBUG logging
juju model-config logging-config="<root>=INFO;unit=DEBUG"
juju deploy ./traefik-k8s_ubuntu-20.04-amd64.charm traefik-ingress --trust --resource traefik-image=localhost:32000/traefik:v1
```
