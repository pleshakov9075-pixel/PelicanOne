#!/usr/bin/env bash
set -euo pipefail

TARGET_DIR=${1:-/opt/pelicanone/data}
find "$TARGET_DIR" -type f -mtime +7 -delete
