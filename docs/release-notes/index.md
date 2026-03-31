---
myst:
  html_meta:
    "description lang=en": "History of stable releases for the Traefik charm."
---

(release_notes_index)=

# Release notes

Release notes for the `latest/stable` track of Traefik, summarizing new features,
bug fixes and backwards-incompatible changes in each revision.

For upgrading the charm, see [How to upgrade](how_to_upgrade).
For instructions on a specific release, see the corresponding release notes.

## Release policy and schedule

For any given track, we'll implement three different risk levels `edge`, `candidate`, and `stable`. The release schedule for each of the risk levels is as follows:

1. Changes pushed to the `traefik-k8s-operator` repository will be released to `edge`.
2. On Monday of every two weeks, the current revision on `candidate` will be promoted to `stable`. This process requires an approval from the maintainers and happens automatically once the approval is given.
3. On Monday of every two weeks, the current revision on `edge` will be promoted to `candidate`. This process also requires an approval from the maintainers and happens automatically once the approval is given.

In special cases where an urgent fix is needed on `stable`, changes can be pushed directly to that risk level without going through the regular process.

Release notes are published for the `traefik-k8s` charm with every revision of the `latest/stable` track.

## Releases

```{toctree}
:hidden:
:maxdepth: 1
```
