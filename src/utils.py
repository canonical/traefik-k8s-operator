#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""Utilities."""

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
