#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This module tests that traefik ends up in active state when deployed AFTER metallb.

...And without the help of update-status.

1. Enable metallb (in case it's disabled).
2. Deploy traefik + one charm per relation type (as if deployed as part of a bundle).

NOTE: This module implicitly relies on in-order execution (test running in the order they are
 written).
"""
