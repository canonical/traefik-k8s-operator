#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Utilities."""

import hashlib
import ipaddress
from typing import Optional


def is_hostname(value: Optional[str]) -> bool:
    """Return False if input value is an IP address; True otherwise."""
    if value is None:
        return False

    try:
        ipaddress.ip_address(value)
        # No exception raised so this is an IP address.
        return False
    except ValueError:
        # This is not an IP address so assume it's a hostname.
        return bool(value)


def hash(content: str) -> int:
    """Returh the md5 hash of a string.

    Using the builtin `hash` function is not consistent across interpreter
    runs, as it relies on a pseudo-random salt that is calculated that differs
    on every run.
    """
    return int(hashlib.md5(content.encode()).hexdigest(), 16)
