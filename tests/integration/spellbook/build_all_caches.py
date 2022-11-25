# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from tests.integration.spellbook.cache import spellbook_fetch

traefik_root = Path(__file__).parent.parent.parent.parent
testers_root = Path(__file__).parent.parent / "testers"


def main():
    spellbook_fetch(
        charm_name="fockit",
        charm_root=traefik_root,
        hash_paths=[
            traefik_root / "src",
            traefik_root / "lib",
            traefik_root / "metadata.yaml",
            traefik_root / "config.yaml",
            traefik_root / "charmcraft.yaml",
        ],
    )
    spellbook_fetch(
        charm_name="route-tester",
        charm_root=testers_root / "route",
        pull_libs=[
            traefik_root / "lib" / "charms" / "traefik_route_k8s" / "v0" / "traefik_route.py"
        ],
    )
    # spellbook_fetch(
    #     charm_name="ipa-tester",
    #     charm_root=testers_root / "ipa",
    #     pull_libs=[traefik_root / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress.py"],
    # )
    # spellbook_fetch(
    #     charm_name="ipu-tester",
    #     charm_root=testers_root / "ipu",
    #     pull_libs=[traefik_root / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress_per_unit.py"],
    # )
    # spellbook_fetch(
    #     charm_name="tcp-tester",
    #     charm_root=testers_root / "tcp",
    #     pull_libs=[traefik_root / "lib" / "charms" / "traefik_k8s" / "v1" / "ingress_per_unit.py"],
    # )


if __name__ == "__main__":
    main()
