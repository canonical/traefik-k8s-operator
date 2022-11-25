# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
from pathlib import Path

from tests.integration.spellbook.cache import spellbook_fetch

testers_root = Path(__file__).parent.parent / "testers"


def main():
    spellbook_fetch("route-tester", testers_root / "route"),
    spellbook_fetch("ipa-tester", testers_root / "ipa"),
    spellbook_fetch("ipu-tester", testers_root / "ipu"),
    spellbook_fetch("tcp-tester", testers_root / "tcp"),


if __name__ == "__main__":
    main()
