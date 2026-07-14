#!/bin/bash
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

set -euo pipefail

S3_ACCESS_KEY="my-lovely-key"
S3_SECRET_KEY="this-is-very-secret"
S3_BUCKET="tests"

log() {
    echo "[s3-installation $(date -u +%H:%M:%S)] $*"
}

on_error() {
    log "FAILED at line $1: $2"
    log "Diagnostics:"
    sudo microceph status || true
    sudo snap services microceph || true
    sudo ss -tlnp || true
}

trap 'on_error "${LINENO}" "${BASH_COMMAND}"' ERR

log "Installing microceph snap..."
sudo snap install microceph
log "Bootstrapping microceph cluster..."
sudo microceph cluster bootstrap
log "Adding loopback OSD disk..."
sudo microceph disk add loop,1G,3
log "Enabling RGW on port 7480 (this can take a couple of minutes)..."
sudo microceph enable rgw --port 7480 --wait
log "RGW enabled."

log "Waiting for RGW endpoint to respond..."
curl --connect-timeout 2 --max-time 5 --retry 30 --retry-delay 4 --retry-all-errors -s -o /dev/null \
    http://127.0.0.1:7480
log "RGW endpoint is responding."

log "Creating ci-user..."
sudo microceph.radosgw-admin user create --uid ci-user --display-name "CI User" --access-key "${S3_ACCESS_KEY}" --secret-key "${S3_SECRET_KEY}"
log "ci-user created."

# Create bucket
log "Creating bucket ${S3_BUCKET}..."
curl -sf -X PUT "http://127.0.0.1:7480/${S3_BUCKET}" --aws-sigv4 "aws:amz:us-east-1:s3" --user "${S3_ACCESS_KEY}:${S3_SECRET_KEY}"
log "Bucket ${S3_BUCKET} created. s3-installation.sh complete."
