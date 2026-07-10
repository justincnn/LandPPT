#!/bin/sh

set -eu

TARGET_UID="${LANDPPT_UID:-10001}"
TARGET_GID="${LANDPPT_GID:-10001}"
MOUNT_ROOT="/mnt/landppt"
MARKER_NAME=".landppt-permissions-v1"

log() {
    printf '[permissions-init] %s\n' "$1"
}

warn() {
    printf '[permissions-init] WARNING: %s\n' "$1" >&2
}

fail() {
    printf '[permissions-init] ERROR: %s\n' "$1" >&2
    exit 1
}

validate_access() {
    target_path="$1"
    target_kind="$2"

    if ! /opt/venv/bin/python - "$TARGET_UID" "$TARGET_GID" "$target_path" "$target_kind" <<'PY'
import os
import sys

uid = int(sys.argv[1])
gid = int(sys.argv[2])
path = sys.argv[3]
kind = sys.argv[4]

os.setgroups([])
os.setgid(gid)
os.setuid(uid)

if kind == "file":
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND)
    os.close(descriptor)
else:
    probe = os.path.join(path, f".landppt-write-test-{os.getpid()}")
    descriptor = os.open(probe, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    os.close(descriptor)
    os.unlink(probe)
PY
    then
        fail "UID ${TARGET_UID} cannot write ${target_path}"
    fi
}

migrate_volume() {
    volume_path="$1"
    marker_path="${volume_path}/${MARKER_NAME}"

    [ -d "$volume_path" ] || fail "Volume path is missing: ${volume_path}"

    if [ ! -f "$marker_path" ]; then
        log "Migrating ${volume_path} to ${TARGET_UID}:${TARGET_GID}"
        chown -R "${TARGET_UID}:${TARGET_GID}" "$volume_path"
        chmod -R u+rwX "$volume_path"
        validate_access "$volume_path" directory
        : > "$marker_path"
        chown "${TARGET_UID}:${TARGET_GID}" "$marker_path"
        chmod 600 "$marker_path"
    else
        log "Migration marker found for ${volume_path}; validating"
        validate_access "$volume_path" directory
    fi
}

configure_env_file() {
    env_path="${MOUNT_ROOT}/env/.env"

    [ -e "$env_path" ] || fail "Mounted .env is missing: ${env_path}"
    [ -f "$env_path" ] || fail "Mounted .env is not a regular file: ${env_path}"

    if ! chgrp "$TARGET_GID" "$env_path" 2>/dev/null; then
        warn "Could not change .env group; checking effective access"
    fi
    if ! chmod g+rw,o-rwx "$env_path" 2>/dev/null; then
        warn "Could not change .env mode; checking effective access"
    fi

    validate_access "$env_path" file
}

main() {
    [ "$(id -u)" -eq 0 ] || fail "Permission migration must run as root"

    configure_env_file
    for volume_name in data uploads reports cache lib; do
        migrate_volume "${MOUNT_ROOT}/${volume_name}"
    done

    log "Permission migration complete"
}

main "$@"
