#!/bin/bash
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

S3_ACCESS_KEY="my-lovely-key"
S3_SECRET_KEY="this-is-very-secret"
S3_BUCKET="tests"

sudo snap install microceph
sudo microceph cluster bootstrap
sudo microceph disk add loop,1G,3
sudo microceph enable rgw --port 7480 --wait

curl --connect-timeout 2 --max-time 3 --retry 5 --retry-delay 2 --retry-connrefused -s http://127.0.0.1:7480

sudo microceph.radosgw-admin user create --uid ci-user --display-name "CI User" --access-key "${S3_ACCESS_KEY}" --secret-key "${S3_SECRET_KEY}"

# Create bucket
curl -sf -X PUT "http://127.0.0.1:7480/${S3_BUCKET}" --aws-sigv4 "aws:amz:us-east-1:s3" --user "${S3_ACCESS_KEY}:${S3_SECRET_KEY}"
