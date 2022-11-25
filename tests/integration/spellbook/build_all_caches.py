# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from tests.integration.spellbook.cache import build_charm_or_fetch_cached

testers_root = Path(__file__).parent.parent / "testers"


def main():
    build_charm_or_fetch_cached("route-tester", testers_root / "route"),
    build_charm_or_fetch_cached("ipa-tester", testers_root / "ipa"),
    build_charm_or_fetch_cached("ipu-tester", testers_root / "ipu"),
    build_charm_or_fetch_cached("tcp-tester", testers_root / "tcp"),


if __name__ == "__main__":
    main()
