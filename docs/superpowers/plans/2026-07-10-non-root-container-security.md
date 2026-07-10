# Non-Root Container Security Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the LandPPT image and all long-lived application workloads run as fixed non-root UID/GID `10001`, while automatically migrating existing Compose volumes and Helm PVC permissions.

**Architecture:** The image declares `USER landppt` after all privileged build work. Docker Compose uses a capability-restricted, networkless one-shot service to migrate legacy volume ownership before web or worker startup; Kubernetes uses `fsGroup` with `OnRootMismatch`. Static regression tests lock the Dockerfile, entrypoint, Compose, migration script, and Helm manifests to the approved security contract.

**Tech Stack:** Dockerfile, POSIX shell, Docker Compose, Helm/Kubernetes YAML, Python 3.11, pytest.

## Global Constraints

- The runtime identity is fixed at UID/GID `10001` in the image, Compose migration, and Helm defaults.
- Web, worker, health-check, and application migration commands must not run as UID `0`.
- Existing repository-supported Compose named volumes and Helm PVCs must migrate without operator commands.
- The Compose root helper must not mount `/app`, the source tree, the Docker socket, or any application network.
- The Compose root helper drops all capabilities except `CHOWN`, `FOWNER`, `DAC_OVERRIDE`, `SETUID`, and `SETGID`.
- `.env` must remain writable by the application configuration flow but must not be mode `0666` in the image.
- Volume migration is idempotent through `.landppt-permissions-v1` markers.
- Permission validation fails closed and identifies the exact inaccessible path.
- Direct hand-written `docker run` commands attaching legacy volumes are outside the automatic migration guarantee.
- Do not dismiss or suppress Trivy `DS-0002`.

---

## File Structure

- Create `tests/test_container_security.py`
  - Owns static regression coverage for the Dockerfile, entrypoint, Compose services, migration script, and Helm templates.
- Create `docker-permissions-init.sh`
  - Owns the one-shot migration of Compose-mounted `.env` and named volumes; it never starts LandPPT.
- Modify `Dockerfile`
  - Creates fixed UID/GID `10001`, installs the migration script, sets secure ownership/modes, and declares `USER landppt`.
- Modify `docker-entrypoint.sh`
  - Removes privileged repair behavior and performs non-root identity and path preflight checks.
- Modify `docker-compose.yml`
  - Adds the production `permissions-init` service and makes web/worker wait for it.
- Modify `docker-compose-dev.yaml`
  - Adds the source-mounted development stack's isolated `permissions-init` service without mounting the repository into it.
- Modify `helm/landppt/values.yaml`
  - Supplies secure non-root pod/container defaults and PVC group migration policy.
- Modify `helm/landppt/templates/worker-deployment.yaml`
  - Renders both pod and container security contexts for the worker, matching web and migration workloads.

---

### Task 1: Non-Root Runtime Image and Fail-Closed Entrypoint

**Files:**
- Create: `tests/test_container_security.py`
- Modify: `Dockerfile:70-185`
- Modify: `docker-entrypoint.sh:105-218`

**Interfaces:**
- Produces: image account `landppt` with UID/GID `10001`
- Produces: final Docker image metadata `Config.User=landppt`
- Produces: entrypoint functions `check_runtime_identity()`, `check_env_permissions()`, and `create_directories()`
- Consumes: existing runtime paths `/app/.env`, `/app/data`, `/app/uploads`, `/app/temp`, `/app/research_reports`, and `/app/lib`

- [ ] **Step 1: Write failing image and entrypoint security tests**

Create `tests/test_container_security.py` with:

```python
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]


def read_repo_file(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def production_stage(dockerfile: str) -> str:
    return dockerfile.split(
        "FROM python:3.11-slim-bookworm AS production", 1
    )[1]


def test_runtime_image_uses_fixed_non_root_identity():
    stage = production_stage(read_repo_file("Dockerfile"))

    assert "ARG LANDPPT_UID=10001" in stage
    assert "ARG LANDPPT_GID=10001" in stage
    assert "groupadd --gid \"${LANDPPT_GID}\" landppt" in stage
    assert "useradd --uid \"${LANDPPT_UID}\"" in stage
    assert "HOME=/home/landppt" in stage
    assert "chmod 640 /app/.env" in stage
    assert "chmod 666 /app/.env" not in stage
    assert "\nUSER landppt\n" in stage
    assert stage.rfind("USER landppt") < stage.find("HEALTHCHECK")


def test_entrypoint_checks_identity_and_never_repairs_permissions():
    entrypoint = read_repo_file("docker-entrypoint.sh")

    assert "check_runtime_identity()" in entrypoint
    assert 'if [ "$(id -u)" -eq 0 ]; then' in entrypoint
    assert "LandPPT must not run as root" in entrypoint
    assert "check_env_permissions()" in entrypoint
    assert "Required path is not writable" in entrypoint
    assert "fix_env_permissions" not in entrypoint
    assert "chmod " not in entrypoint
    assert "chown " not in entrypoint
    assert 'cp "/app/.env"' not in entrypoint
```

- [ ] **Step 2: Run the focused tests and verify the current root image fails**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
```

Expected: two failures because the production stage has no fixed UID/GID or final `USER`, and the entrypoint still contains `fix_env_permissions()`.

- [ ] **Step 3: Give the production image a fixed non-root identity**

In `Dockerfile`, insert the identity arguments immediately after the production `FROM`:

```dockerfile
FROM python:3.11-slim-bookworm AS production

ARG LANDPPT_UID=10001
ARG LANDPPT_GID=10001
```

Change the production environment's home entry to:

```dockerfile
    HOME=/home/landppt \
```

Replace the current account creation block with:

```dockerfile
# Create a stable non-root runtime identity.
RUN groupadd --gid "${LANDPPT_GID}" landppt && \
    useradd --uid "${LANDPPT_UID}" \
            --gid landppt \
            --create-home \
            --home-dir /home/landppt \
            --shell /usr/sbin/nologin \
            landppt
```

Change the final `.env` mode in the directory permission layer:

```dockerfile
    chmod 640 /app/.env
```

Add the user switch immediately before `EXPOSE 8000`:

```dockerfile
# Run the entrypoint, health check, web process, worker, and CLI as non-root.
USER landppt
```

- [ ] **Step 4: Replace privileged entrypoint repair with explicit preflight checks**

Replace the existing `create_directories()` function in `docker-entrypoint.sh` with:

```bash
# Create and verify runtime directories as the application user.
create_directories() {
    log "Checking runtime directories..."

    local dirs=(
        "/app/data"
        "/app/uploads"
        "/app/temp/ai_responses_cache"
        "/app/temp/style_genes_cache"
        "/app/temp/summeryanyfile_cache"
        "/app/temp/templates_cache"
        "/app/research_reports"
        "/app/lib/Linux"
        "/app/lib/MacOS"
        "/app/lib/Windows"
    )

    for dir in "${dirs[@]}"; do
        if ! mkdir -p "$dir" 2>/dev/null; then
            error "Required path cannot be created: $dir"
            return 1
        fi
        if [ ! -w "$dir" ] || [ ! -x "$dir" ]; then
            error "Required path is not writable: $dir"
            return 1
        fi
    done
}
```

Replace the entire current `fix_env_permissions()` function with:

```bash
# Refuse to start with a privileged identity.
check_runtime_identity() {
    if [ "$(id -u)" -eq 0 ]; then
        error "LandPPT must not run as root"
        return 1
    fi

    info "Running as uid=$(id -u) gid=$(id -g)"
}

# Validate .env access without trying to mutate mounted host files.
check_env_permissions() {
    log "Checking .env file permissions..."

    if [ ! -e "/app/.env" ]; then
        warn ".env file not found, using process environment only"
        return 0
    fi
    if [ ! -f "/app/.env" ]; then
        error "Required path is not a regular file: /app/.env"
        return 1
    fi
    if [ ! -r "/app/.env" ]; then
        error "Required path is not readable: /app/.env"
        return 1
    fi
    if [ ! -w "/app/.env" ]; then
        error "Required path is not writable: /app/.env"
        return 1
    fi

    log ".env file is readable and writable"
}
```

Update the initialization calls in `main()` to this order:

```bash
    check_runtime_identity
    check_environment
    check_env_permissions
    create_directories
    wait_for_dependencies
    import_templates
```

- [ ] **Step 5: Run the focused tests and shell syntax check**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
bash -n docker-entrypoint.sh
```

Expected: pytest reports `2 passed`; `bash -n` exits `0` with no output.

- [ ] **Step 6: Commit the non-root image boundary**

```bash
git add Dockerfile docker-entrypoint.sh tests/test_container_security.py
git commit -m "fix(docker): run LandPPT as non-root"
```

---

### Task 2: Automatic Compose Volume Permission Migration

**Files:**
- Create: `docker-permissions-init.sh`
- Modify: `Dockerfile:164-174`
- Modify: `docker-compose.yml:46-98`
- Modify: `docker-compose-dev.yaml:53-110`
- Modify: `tests/test_container_security.py`

**Interfaces:**
- Produces: `/usr/local/bin/docker-permissions-init.sh`
- Produces: Compose service `permissions-init`
- Produces: marker contract `<volume>/.landppt-permissions-v1`
- Consumes: environment variables `LANDPPT_UID` and `LANDPPT_GID`, both defaulting to `10001`
- Consumes: mounts `/mnt/landppt/env/.env`, `/mnt/landppt/data`, `/mnt/landppt/uploads`, `/mnt/landppt/reports`, `/mnt/landppt/cache`, and `/mnt/landppt/lib`

- [ ] **Step 1: Add failing Compose and migration-script tests**

Append this code to `tests/test_container_security.py`:

```python
def compose_init_service(compose_text: str) -> str:
    return compose_text.split("\n  permissions-init:\n", 1)[1].split(
        "\n  landppt:\n", 1
    )[0]


def compose_dependency_anchor(compose_text: str) -> str:
    return compose_text.split(
        "x-landppt-depends-on: &landppt-depends-on", 1
    )[1].split("\n\nservices:", 1)[0]


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "docker-compose-dev.yaml"])
def test_compose_migrates_permissions_before_app_start(compose_path: str):
    compose_text = read_repo_file(compose_path)
    init_service = compose_init_service(compose_text)
    dependencies = compose_dependency_anchor(compose_text)

    assert 'user: "0:0"' in init_service
    assert 'entrypoint: ["/usr/local/bin/docker-permissions-init.sh"]' in init_service
    assert 'network_mode: "none"' in init_service
    assert "read_only: true" in init_service
    assert 'restart: "no"' in init_service
    assert "- ALL" in init_service
    for capability in ("CHOWN", "FOWNER", "DAC_OVERRIDE", "SETUID", "SETGID"):
        assert f"- {capability}" in init_service
    assert "no-new-privileges:true" in init_service

    for mount in (
        "${LANDPPT_ENV_FILE:-./.env}:/mnt/landppt/env/.env",
        "landppt_data:/mnt/landppt/data",
        "landppt_uploads:/mnt/landppt/uploads",
        "landppt_reports:/mnt/landppt/reports",
        "landppt_cache:/mnt/landppt/cache",
        "landppt_lib:/mnt/landppt/lib",
    ):
        assert mount in init_service

    assert "/app" not in init_service
    assert "${LANDPPT_ENV_FILE:-./.env}:/app/.env" in compose_text
    assert "permissions-init:" in dependencies
    assert "condition: service_completed_successfully" in dependencies


def test_permission_migration_script_is_idempotent_and_validates_as_target_user():
    script = read_repo_file("docker-permissions-init.sh")
    dockerfile = read_repo_file("Dockerfile")

    assert ".landppt-permissions-v1" in script
    assert 'LANDPPT_UID:-10001' in script
    assert 'LANDPPT_GID:-10001' in script
    assert "os.setgid(gid)" in script
    assert "os.setuid(uid)" in script
    assert 'chown -R "${TARGET_UID}:${TARGET_GID}"' in script
    assert "chmod -R u+rwX" in script
    assert "docker-permissions-init.sh /usr/local/bin/" in dockerfile
```

- [ ] **Step 2: Run the focused tests and verify Compose migration is missing**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
```

Expected: the two Task 1 tests pass; three new cases fail because `permissions-init` and `docker-permissions-init.sh` do not exist.

- [ ] **Step 3: Implement the one-shot permission migration script**

Create `docker-permissions-init.sh` with:

```bash
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
```

- [ ] **Step 4: Install the migration script in the image**

Change the script copy line in `Dockerfile` to:

```dockerfile
COPY docker-healthcheck.sh docker-entrypoint.sh docker-permissions-init.sh /usr/local/bin/
```

Change the executable-mode command to:

```dockerfile
    chmod +x /usr/local/bin/docker-healthcheck.sh \
             /usr/local/bin/docker-entrypoint.sh \
             /usr/local/bin/docker-permissions-init.sh && \
```

- [ ] **Step 5: Add the production Compose initializer and dependency**

In `x-landppt-volumes` in `docker-compose.yml`, replace the fixed `.env` bind with this configurable bind so the application and initializer always operate on the same file:

```yaml
  - ${LANDPPT_ENV_FILE:-./.env}:/app/.env
```

Add this dependency to `x-landppt-depends-on` in `docker-compose.yml`:

```yaml
  permissions-init:
    condition: service_completed_successfully
```

Add this service immediately after `services:` and before `landppt`:

```yaml
  permissions-init:
    image: ${LANDPPT_IMAGE:-bradleylzh/landppt:latest}
    user: "0:0"
    entrypoint: ["/usr/local/bin/docker-permissions-init.sh"]
    environment:
      LANDPPT_UID: "10001"
      LANDPPT_GID: "10001"
    volumes:
      - ${LANDPPT_ENV_FILE:-./.env}:/mnt/landppt/env/.env
      - landppt_data:/mnt/landppt/data
      - landppt_uploads:/mnt/landppt/uploads
      - landppt_reports:/mnt/landppt/reports
      - landppt_cache:/mnt/landppt/cache
      - landppt_lib:/mnt/landppt/lib
    network_mode: "none"
    read_only: true
    restart: "no"
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - FOWNER
      - DAC_OVERRIDE
      - SETUID
      - SETGID
    security_opt:
      - no-new-privileges:true
    healthcheck:
      disable: true
```

- [ ] **Step 6: Add the development Compose initializer without the source bind mount**

In `docker-compose-dev.yaml`, add an explicit `.env` bind immediately after the existing `./:/app` source bind. This makes the environment file overridable while the initializer remains isolated from the rest of the source tree:

```yaml
  - ${LANDPPT_ENV_FILE:-./.env}:/app/.env
```

Add the same `permissions-init` dependency to `x-landppt-depends-on` in `docker-compose-dev.yaml`.

Add this service immediately after `services:` and before `landppt`:

```yaml
  permissions-init:
    build: *landppt-build
    image: ${LANDPPT_DEV_IMAGE:-landppt-dev:latest}
    user: "0:0"
    entrypoint: ["/usr/local/bin/docker-permissions-init.sh"]
    environment:
      LANDPPT_UID: "10001"
      LANDPPT_GID: "10001"
    volumes:
      - ${LANDPPT_ENV_FILE:-./.env}:/mnt/landppt/env/.env
      - landppt_data:/mnt/landppt/data
      - landppt_uploads:/mnt/landppt/uploads
      - landppt_reports:/mnt/landppt/reports
      - landppt_cache:/mnt/landppt/cache
      - landppt_lib:/mnt/landppt/lib
    network_mode: "none"
    read_only: true
    restart: "no"
    cap_drop:
      - ALL
    cap_add:
      - CHOWN
      - FOWNER
      - DAC_OVERRIDE
      - SETUID
      - SETGID
    security_opt:
      - no-new-privileges:true
    healthcheck:
      disable: true
```

Do not reuse `*landppt-volumes` for this service: that anchor contains `./:/app` and would expose the whole repository to the root helper.

- [ ] **Step 7: Validate the script, Compose models, and focused tests**

Run:

```bash
bash -n docker-permissions-init.sh
docker compose config --quiet
docker compose -f docker-compose-dev.yaml config --quiet
uv run --extra dev pytest tests/test_container_security.py -q
```

Expected: both shell/Compose checks exit `0`; pytest reports `5 passed`.

- [ ] **Step 8: Commit the automatic Compose migration**

```bash
git add Dockerfile docker-permissions-init.sh docker-compose.yml docker-compose-dev.yaml tests/test_container_security.py
git commit -m "fix(docker): migrate volumes before non-root startup"
```

---

### Task 3: Helm Non-Root Enforcement and PVC Group Migration

**Files:**
- Modify: `helm/landppt/values.yaml:171-172`
- Modify: `helm/landppt/templates/worker-deployment.yaml:24-83`
- Modify: `tests/test_container_security.py`

**Interfaces:**
- Produces: `.Values.podSecurityContext` defaults for PVC ownership policy and seccomp
- Produces: `.Values.securityContext` defaults for UID/GID, non-root enforcement, privilege escalation, and capabilities
- Consumes: the image identity `10001:10001` created in Task 1

- [ ] **Step 1: Add failing Helm security-context tests**

Append this code to `tests/test_container_security.py`:

```python
def test_helm_defaults_enforce_non_root_identity_and_volume_group():
    values = read_repo_file("helm/landppt/values.yaml")
    pod_context = values.split("podSecurityContext:", 1)[1].split(
        "\nsecurityContext:", 1
    )[0]
    container_context = values.split("\nsecurityContext:", 1)[1].split(
        "\nlivenessProbe:", 1
    )[0]

    for expected in (
        "fsGroup: 10001",
        "fsGroupChangePolicy: OnRootMismatch",
        "type: RuntimeDefault",
    ):
        assert expected in pod_context
    assert "runAsUser" not in pod_context

    for expected in (
        "runAsNonRoot: true",
        "runAsUser: 10001",
        "runAsGroup: 10001",
        "allowPrivilegeEscalation: false",
        "- ALL",
    ):
        assert expected in container_context


@pytest.mark.parametrize(
    "template_path",
    [
        "helm/landppt/templates/deployment.yaml",
        "helm/landppt/templates/worker-deployment.yaml",
        "helm/landppt/templates/migration-job.yaml",
    ],
)
def test_helm_workloads_render_pod_and_container_security_contexts(
    template_path: str,
):
    template = read_repo_file(template_path)

    assert "{{- with .Values.podSecurityContext }}" in template
    assert "{{- with .Values.securityContext }}" in template
```

- [ ] **Step 2: Run focused tests and verify Helm defaults and worker fail**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
```

Expected: Task 1 and Task 2 tests pass; the defaults test fails, and the worker template case fails because it renders neither security context.

- [ ] **Step 3: Set secure chart defaults**

Replace the two empty security-context objects in `helm/landppt/values.yaml` with:

```yaml
podSecurityContext:
  fsGroup: 10001
  fsGroupChangePolicy: OnRootMismatch
  seccompProfile:
    type: RuntimeDefault

securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  allowPrivilegeEscalation: false
  capabilities:
    drop:
      - ALL
```

- [ ] **Step 4: Render the pod security context in the worker deployment**

In `helm/landppt/templates/worker-deployment.yaml`, add this block after `imagePullSecrets` and before `initContainers`:

```yaml
      {{- with .Values.podSecurityContext }}
      securityContext:
        {{- toYaml . | nindent 8 }}
      {{- end }}
```

- [ ] **Step 5: Render the container security context in the worker deployment**

Add this block immediately after the worker's `imagePullPolicy`:

```yaml
          {{- with .Values.securityContext }}
          securityContext:
            {{- toYaml . | nindent 12 }}
          {{- end }}
```

- [ ] **Step 6: Run focused tests and render the chart**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
helm lint helm/landppt
helm template landppt helm/landppt --output-dir artifacts/helm-rendered
```

Expected: pytest reports `9 passed`; Helm lint reports `0 chart(s) failed`; the rendered web, worker, and migration pod specs contain UID/GID `10001`, and persisted pods contain `fsGroup: 10001`.

- [ ] **Step 7: Commit the Helm security boundary**

```bash
git add helm/landppt/values.yaml helm/landppt/templates/worker-deployment.yaml tests/test_container_security.py
git commit -m "fix(helm): enforce non-root LandPPT workloads"
```

---

### Task 4: Security Scan, Runtime Migration Exercise, and Final Regression

**Files:**
- Verify: `Dockerfile`
- Verify: `docker-entrypoint.sh`
- Verify: `docker-permissions-init.sh`
- Verify: `docker-compose.yml`
- Verify: `docker-compose-dev.yaml`
- Verify: `helm/landppt/values.yaml`
- Verify: `helm/landppt/templates/worker-deployment.yaml`
- Verify: `tests/test_container_security.py`

**Interfaces:**
- Consumes: all artifacts from Tasks 1-3
- Produces: verified Trivy result with no `DS-0002`
- Produces: evidence that a root-owned legacy volume becomes writable by UID/GID `10001`

- [ ] **Step 1: Run the focused and full pytest suites**

Run:

```bash
uv run --extra dev pytest tests/test_container_security.py -q
uv run --extra dev pytest -q
```

Expected: focused tests report `9 passed`; the full suite passes. If an unrelated environment dependency blocks the full suite, preserve the exact command and error in the final handoff.

- [ ] **Step 2: Validate shell, Compose, and Helm syntax**

Run:

```bash
bash -n docker-entrypoint.sh docker-permissions-init.sh
docker compose config --quiet
docker compose -f docker-compose-dev.yaml config --quiet
helm lint helm/landppt
helm template landppt helm/landppt --output-dir artifacts/helm-rendered
```

Expected: every command exits `0`; Helm reports `0 chart(s) failed`.

- [ ] **Step 3: Run the same Trivy configuration class that opened the alert**

Run:

```bash
trivy config --severity HIGH,CRITICAL --exit-code 1 .
```

Expected: exit `0` and no `DS-0002` finding for `Dockerfile`. If Trivy is not installed locally, record `trivy: command not found` and rely on the existing GitHub `security-scan` workflow after push; do not add an ignore rule.

- [ ] **Step 4: Build and inspect the image when a Docker daemon is available**

Run in PowerShell:

```powershell
$image = "landppt-security-test:local"
docker build -t $image .
docker image inspect $image --format '{{.Config.User}}'
docker run --rm --entrypoint /usr/bin/id $image -u
docker run --rm --entrypoint /usr/bin/id $image -g
```

Expected: build succeeds; inspection prints `landppt`; both `id` commands print `10001`.

- [ ] **Step 5: Exercise automatic migration against isolated root-owned volumes**

Run in PowerShell; these names are isolated from the developer's normal Compose project:

```powershell
$project = "landppt-security-test"
$image = "landppt-security-test:local"
$envFile = ".tmp/landppt-security-test.env"
New-Item -ItemType Directory -Force .tmp | Out-Null
Copy-Item -LiteralPath .env.example -Destination $envFile -Force
$env:LANDPPT_ENV_FILE = $envFile
$env:LANDPPT_IMAGE = $image
$volumeKeys = @("landppt_data", "landppt_uploads", "landppt_reports", "landppt_cache", "landppt_lib")
docker compose -p $project create permissions-init
foreach ($key in $volumeKeys) {
    $volume = "${project}_${key}"
    docker run --rm --user "0:0" --entrypoint /bin/sh -v "${volume}:/legacy" $image -c "mkdir -p /legacy/root-owned; echo legacy > /legacy/root-owned/value.txt; chown -R 0:0 /legacy"
}
docker compose -p $project run --rm --no-deps permissions-init
docker compose -p $project run --rm --no-deps permissions-init
docker run --rm --entrypoint /bin/sh -v "${project}_landppt_data:/legacy" $image -c "test -f /legacy/.landppt-permissions-v1 && test -w /legacy/root-owned/value.txt"
```

Expected: both initializer runs exit `0`; the second run logs that markers were found; the final non-root write check exits `0`.

- [ ] **Step 6: Clean up only the isolated runtime-test resources**

Run in PowerShell:

```powershell
docker compose -p landppt-security-test down -v
docker image rm landppt-security-test:local
Remove-Item Env:\LANDPPT_IMAGE -ErrorAction SilentlyContinue
Remove-Item Env:\LANDPPT_ENV_FILE -ErrorAction SilentlyContinue
Remove-Item -LiteralPath .tmp\landppt-security-test.env -Force -ErrorAction SilentlyContinue
```

Expected: only resources prefixed `landppt-security-test` and the local test image are removed. Do not run this cleanup with the repository's normal Compose project name.

- [ ] **Step 7: Review the final diff against the security contract**

Run:

```bash
git diff HEAD~3 -- Dockerfile docker-entrypoint.sh docker-permissions-init.sh docker-compose.yml docker-compose-dev.yaml helm/landppt/values.yaml helm/landppt/templates/worker-deployment.yaml tests/test_container_security.py
git diff --check
```

Confirm:

- The final image user is `landppt` and no privileged runtime command follows `USER landppt`.
- The helper mounts only `.env` and the five named volumes.
- Long-lived Compose services do not override the image user.
- Web, worker, and migration Helm workloads render non-root contexts.
- No Trivy suppression, `privileged: true`, Docker socket mount, or world-writable image `.env` was added.

- [ ] **Step 8: Commit final fixes only if review or verification required changes**

If Steps 1-7 required corrections, stage only those corrections and commit:

```bash
git add Dockerfile docker-entrypoint.sh docker-permissions-init.sh docker-compose.yml docker-compose-dev.yaml helm/landppt/values.yaml helm/landppt/templates/worker-deployment.yaml tests/test_container_security.py
git commit -m "fix(security): harden non-root container migration"
```

If no corrections were required, do not create an empty commit.

- [ ] **Step 9: Final repository status**

Run:

```bash
git status --short --branch
git log --oneline -8
```

Expected: the working tree is clean, and the Docker, Compose, and Helm commits appear above the design and plan commits.
