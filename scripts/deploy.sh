#!/usr/bin/env bash
# Non-destructive production deployment for Daisy Risk Engine.
#
# Required immutable deployment inputs:
#   BACKEND_IMAGE   non-latest image tag or digest built by CI
#   FRONTEND_IMAGE  non-latest image tag or digest built by CI
#
# The script never prunes Docker resources and never removes named volumes.

set -euo pipefail
# Backup/state artifacts must never be created world-readable.
umask 077

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

APP_NAME="daisy-risk-engine"
COMPOSE_FILE="docker-compose.prod.yml"
ENVIRONMENT="production"
PUBLIC_BASE_URL="${PUBLIC_BASE_URL:-http://127.0.0.1}"
STATE_DIR="${DEPLOY_STATE_DIR:-.deploy}"
DEPLOY_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1" >&2; }

compose() {
    if docker compose version >/dev/null 2>&1; then
        docker compose -f "$COMPOSE_FILE" "$@"
    elif command -v docker-compose >/dev/null 2>&1; then
        docker-compose -f "$COMPOSE_FILE" "$@"
    else
        log_error "Docker Compose is not available."
        return 1
    fi
}

check_dependencies() {
    log_info "Checking Docker, Compose, and curl..."
    command -v docker >/dev/null 2>&1 || { log_error "Docker is required."; return 1; }
    command -v curl >/dev/null 2>&1 || { log_error "curl is required for published health probes."; return 1; }
    compose version >/dev/null || return 1
}

validate_image_ref() {
    local name="$1"
    local value="$2"
    if [[ -z "$value" || "$value" == *:latest ]]; then
        log_error "$name must be a non-empty, non-latest tag or digest."
        return 1
    fi
}

check_environment() {
    log_info "Checking immutable image and health configuration..."
    validate_image_ref BACKEND_IMAGE "${BACKEND_IMAGE:-}" || return 1
    validate_image_ref FRONTEND_IMAGE "${FRONTEND_IMAGE:-}" || return 1
    [[ "$PUBLIC_BASE_URL" =~ ^https?:// ]] || {
        log_error "PUBLIC_BASE_URL must be an http(s) URL."
        return 1
    }
}

configured_database_path() {
    compose run --rm --no-deps -T backend \
        python -m migrations.sqlite_backup --print-configured-path
}

backup_database() {
    log_info "Creating a verified SQLite backup of the configured database..."
    local db_path container_backup_dir container_backup host_dir host_backup
    db_path="$(configured_database_path)" || return 1
    [[ -n "$db_path" && "$db_path" == /* ]] || {
        log_error "Configured SQLite path did not resolve to an absolute container path: $db_path"
        return 1
    }

    container_backup_dir="$(dirname "$db_path")/backups"
    container_backup="$container_backup_dir/deploy_${DEPLOY_ID}.db"
    host_dir="backups/$ENVIRONMENT"
    host_backup="$host_dir/daisy_${DEPLOY_ID}.db"
    mkdir -p "$host_dir" || return 1

    # The one-off service has the same image, environment, and volume mount as
    # the backend. Set the container process umask before SQLite creates the
    # destination; the host shell's umask does not cross the container boundary.
    compose run --rm --no-deps -T backend sh -c \
        'umask 077; exec python -m migrations.sqlite_backup --source "$1" --destination "$2"' \
        sh "$db_path" "$container_backup" >/dev/null || return 1

    # Reserve the host destination with its final private mode at creation so
    # neither a long-lived file nor Docker's copy process can expose content.
    # noclobber also makes the no-overwrite guarantee atomic.
    if ! (
        set -o noclobber
        umask 077
        : > "$host_backup"
    ); then
        log_error "Refusing to overwrite backup artifact: $host_backup"
        return 1
    fi
    compose cp "backend:$container_backup" "$host_backup" >/dev/null || return 1

    # Verify the host artifact itself through the same image, read-only mounted
    # at a temporary path. Tests additionally restore it with the backup API.
    compose run --rm --no-deps -T \
        --volume "$(pwd)/$host_backup:/tmp/deploy-backup.db:ro" \
        backend python -m migrations.sqlite_backup \
        --source /tmp/deploy-backup.db --verify-only >/dev/null || {
        log_error "Host backup copy failed verification: $host_backup"
        return 1
    }

    BACKUP_ARTIFACT="$host_backup"
    log_info "Backup verified: $host_backup"
}

pull_images() {
    log_info "Pulling the selected backend and frontend image identities..."
    compose pull backend frontend || return 1
}

pin_deployment_images() {
    local backend_id frontend_id
    backend_id="$(docker image inspect --format '{{.Id}}' "$BACKEND_IMAGE")" || return 1
    frontend_id="$(docker image inspect --format '{{.Id}}' "$FRONTEND_IMAGE")" || return 1
    [[ "$backend_id" =~ ^sha256:[0-9a-f]{64}$ ]] || { log_error "Backend image has no immutable ID."; return 1; }
    [[ "$frontend_id" =~ ^sha256:[0-9a-f]{64}$ ]] || { log_error "Frontend image has no immutable ID."; return 1; }

    PINNED_BACKEND_IMAGE="${APP_NAME}-backend:deploy-${DEPLOY_ID}"
    PINNED_FRONTEND_IMAGE="${APP_NAME}-frontend:deploy-${DEPLOY_ID}"
    docker image tag "$backend_id" "$PINNED_BACKEND_IMAGE" || return 1
    docker image tag "$frontend_id" "$PINNED_FRONTEND_IMAGE" || return 1
    export BACKEND_IMAGE="$PINNED_BACKEND_IMAGE"
    export FRONTEND_IMAGE="$PINNED_FRONTEND_IMAGE"
    PINNED_BACKEND_ID="$backend_id"
    PINNED_FRONTEND_ID="$frontend_id"
}

write_identity_file() {
    local path="$1" backend_id="$2" frontend_id="$3"
    [[ "$backend_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    [[ "$frontend_id" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    mkdir -p "$STATE_DIR" || return 1
    umask 077
    printf 'BACKEND_IMAGE_ID=%s\nFRONTEND_IMAGE_ID=%s\nRECORDED_AT=%s\n' \
        "$backend_id" "$frontend_id" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$path" || return 1
}

record_previous_identity() {
    local backend_container frontend_container backend_id frontend_id
    backend_container="$(compose ps -q backend 2>/dev/null || true)"
    frontend_container="$(compose ps -q frontend 2>/dev/null || true)"
    if [[ -z "$backend_container" || -z "$frontend_container" ]]; then
        log_warn "No complete previous service pair exists; rollback is unavailable for this first deployment."
        return 0
    fi
    backend_id="$(docker inspect --format '{{.Image}}' "$backend_container")" || return 1
    frontend_id="$(docker inspect --format '{{.Image}}' "$frontend_container")" || return 1
    if write_identity_file "$STATE_DIR/${ENVIRONMENT}.previous.env" "$backend_id" "$frontend_id"; then
        log_info "Recorded previous image identities for rollback."
    else
        log_warn "Previous image identities were invalid; rollback is unavailable."
    fi
}

deploy_application() {
    log_info "Recreating services with the selected pinned image tags..."
    compose up -d --no-build --force-recreate backend frontend || return 1
}

health_check() {
    log_info "Waiting for published backend and frontend readiness..."
    local backend_url="${PUBLIC_BASE_URL%/}/health"
    local frontend_url="$PUBLIC_BASE_URL"
    local attempt ready=false
    for attempt in $(seq 1 30); do
        if curl -fsS --max-time 5 "$backend_url" >/dev/null 2>&1 \
            && curl -fsS --max-time 5 "$frontend_url" >/dev/null 2>&1; then
            ready=true
            break
        fi
        sleep 2
    done
    if [[ "$ready" != true ]]; then
        log_error "Published service health checks failed: $backend_url $frontend_url"
        return 1
    fi

    compose exec -T backend python -m migrations.sqlite_backup --verify-only >/dev/null || {
        log_error "Backend SQLite quick_check/count verification failed."
        return 1
    }
    log_info "Published HTTP and SQLite readiness checks passed."
}

record_current_identity() {
    write_identity_file \
        "$STATE_DIR/${ENVIRONMENT}.env" \
        "$PINNED_BACKEND_ID" \
        "$PINNED_FRONTEND_ID" || return 1
    rm -f "$STATE_DIR/${ENVIRONMENT}.previous.env" || return 1
}

read_recorded_identity() {
    local state_file="$STATE_DIR/${ENVIRONMENT}.previous.env"
    if [[ ! -f "$state_file" ]]; then
        state_file="$STATE_DIR/${ENVIRONMENT}.env"
    fi
    [[ -f "$state_file" ]] || return 1
    ROLLBACK_BACKEND_ID="$(sed -n 's/^BACKEND_IMAGE_ID=//p' "$state_file")" || return 1
    ROLLBACK_FRONTEND_ID="$(sed -n 's/^FRONTEND_IMAGE_ID=//p' "$state_file")" || return 1
    [[ "$ROLLBACK_BACKEND_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
    [[ "$ROLLBACK_FRONTEND_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || return 1
}

rollback() {
    log_error "Deployment failed; selecting the last recorded known image identities."
    if ! read_recorded_identity; then
        log_error "No valid previous image identity file exists; refusing a same-config restart."
        return 1
    fi

    local rollback_backend="${APP_NAME}-backend:rollback-${DEPLOY_ID}"
    local rollback_frontend="${APP_NAME}-frontend:rollback-${DEPLOY_ID}"
    docker image inspect "$ROLLBACK_BACKEND_ID" >/dev/null 2>&1 || {
        log_error "Recorded backend image ID is no longer available locally."
        return 1
    }
    docker image inspect "$ROLLBACK_FRONTEND_ID" >/dev/null 2>&1 || {
        log_error "Recorded frontend image ID is no longer available locally."
        return 1
    }
    docker image tag "$ROLLBACK_BACKEND_ID" "$rollback_backend" || return 1
    docker image tag "$ROLLBACK_FRONTEND_ID" "$rollback_frontend" || return 1
    export BACKEND_IMAGE="$rollback_backend"
    export FRONTEND_IMAGE="$rollback_frontend"
    if ! compose up -d --no-build --force-recreate backend frontend; then
        log_error "Rollback services failed to start."
        return 1
    fi
    if ! health_check; then
        log_error "Rollback services did not become ready."
        return 1
    fi
    log_info "Rollback selected recorded image IDs and passed readiness checks."
}

print_usage() {
    echo "Usage: BACKEND_IMAGE=... FRONTEND_IMAGE=... $0 production"
}

main() {
    if [[ "${1:-}" == "help" || "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
        print_usage
        return 0
    fi
    if [[ "${1:-}" != "production" ]]; then
        print_usage
        return 2
    fi

    if ! check_dependencies; then
        return 1
    fi
    if ! check_environment; then
        return 1
    fi
    if ! record_previous_identity; then
        log_error "Could not record the previous deployment state."
        return 1
    fi

    local failed=false
    if ! backup_database; then
        failed=true
    elif ! pull_images; then
        failed=true
    elif ! pin_deployment_images; then
        failed=true
    elif ! deploy_application; then
        failed=true
    elif ! health_check; then
        failed=true
    elif ! record_current_identity; then
        failed=true
    fi

    if [[ "$failed" == true ]]; then
        log_error "Deployment stage failed; attempting recorded-image rollback."
        if ! rollback; then
            log_error "Rollback failed. The prior image identity and backup remain recorded for manual recovery."
            return 1
        fi
        return 1
    fi

    log_info "Deployment completed successfully."
    log_info "Backup: ${BACKUP_ARTIFACT:-none}"
    log_info "Health: ${PUBLIC_BASE_URL%/}/health"
}

# Keep functions sourceable for shell/static tests; execute only when invoked.
if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
