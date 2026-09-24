#!/usr/bin/env bash
# Docker-free dry run for deploy.sh rollback image selection.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
source "$ROOT/scripts/deploy.sh"

STATE_DIR="$(mktemp -d)"
trap 'rm -rf "$STATE_DIR"' EXIT
DEPLOY_ID="dry-run"
BACKEND_ID="sha256:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FRONTEND_ID="sha256:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
export STATE_DIR DEPLOY_ID

printf 'BACKEND_IMAGE_ID=%s\nFRONTEND_IMAGE_ID=%s\n' \
    "$BACKEND_ID" "$FRONTEND_ID" > "$STATE_DIR/production.previous.env"

docker() {
    printf 'docker %s\n' "$*" >> "$STATE_DIR/docker.log"
    return 0
}
compose() {
    printf 'compose %s\n' "$*" >> "$STATE_DIR/compose.log"
    return 0
}
health_check() {
    printf 'health_check\n' >> "$STATE_DIR/compose.log"
    return 0
}

rollback

[[ "$BACKEND_IMAGE" == "daisy-risk-engine-backend:rollback-dry-run" ]]
[[ "$FRONTEND_IMAGE" == "daisy-risk-engine-frontend:rollback-dry-run" ]]
grep -F "image tag $BACKEND_ID daisy-risk-engine-backend:rollback-dry-run" "$STATE_DIR/docker.log" >/dev/null
grep -F "image tag $FRONTEND_ID daisy-risk-engine-frontend:rollback-dry-run" "$STATE_DIR/docker.log" >/dev/null
grep -F "up -d --no-build --force-recreate backend frontend" "$STATE_DIR/compose.log" >/dev/null
printf 'PASS rollback selected recorded image IDs and forced recreation without Docker\n'
