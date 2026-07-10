# Non-Root Container Security Design

Date: 2026-07-10

## Goal

Resolve GitHub code-scanning alert 1, Trivy rule `DS-0002` ("Image user should not be 'root'"), by making the LandPPT runtime image non-root by default without requiring operators to repair existing Docker volumes or Kubernetes PVCs manually.

The supported automatic-upgrade paths are the repository's production and development Docker Compose files and the LandPPT Helm chart.

## Current State

The production stage in `Dockerfile` creates a `landppt` account and gives it ownership of application directories, but it does not declare a final `USER`. The image therefore starts the entrypoint, web process, worker process, health check, and migration command as root.

This behavior was introduced in commit `c94c79b7` when `USER landppt` was removed to work around `.env` write permissions. The current entrypoint still contains root-oriented permission repair, and both Compose files bind-mount `.env` while mounting named volumes over the image-owned application directories.

Changing only the final Docker user would close the static alert, but it could break upgrades because prior root processes may have created root-owned content in:

- `/app/data`
- `/app/uploads`
- `/app/research_reports`
- `/app/temp`
- `/app/lib`
- `/app/.env`

The Helm chart exposes `podSecurityContext` and `securityContext` values, but both default to empty objects. The web deployment and migration job consume these values; the worker deployment does not currently consume the container security context.

## Requirements

- The final image must declare a non-root user and satisfy Trivy `DS-0002`.
- Web, worker, health-check, and migration processes must run as the same fixed non-root identity.
- Existing Compose named volumes and Helm-managed PVCs must become writable automatically.
- The Compose migration must not recursively change ownership of the source repository.
- `.env` must remain writable by the application admin configuration flow without becoming world-writable.
- Repeated starts must be idempotent and avoid repeated recursive ownership changes.
- Permission failures must stop startup with an actionable path-specific error.
- Direct, hand-written `docker run` commands that attach legacy volumes are outside the automatic migration guarantee.

## Considered Approaches

### 1. Non-root image with orchestrator-native migration

Use a restricted, one-shot Compose service to migrate named volumes and use Kubernetes `fsGroup` handling for PVCs. Run all long-lived application containers as non-root.

This is the selected approach. It confines elevated access to the minimum Compose migration step and uses Kubernetes' native volume ownership mechanism.

### 2. Root migration containers in both Compose and Kubernetes

Explicit init containers could recursively `chown` every mounted volume. This is deterministic for POSIX storage, but adds a root container to every supported orchestrator and can make large-volume startup slower.

### 3. Add only `USER landppt`

This is the smallest code change and closes the alert, but it can make existing deployments fail with permission errors. It does not meet the automatic-upgrade requirement.

## Image Identity and Filesystem

The production image will create `landppt` with fixed UID and GID `10001`. A fixed numeric identity makes Docker volume ownership, Helm security contexts, and runtime assertions consistent across image rebuilds.

The production-stage environment will set `HOME=/home/landppt`. Build-time package installation, browser installation, code copies, directory creation, and ownership changes will remain before the user switch. The final runtime instructions will declare:

```dockerfile
USER landppt
```

The image-owned `/app/.env` will be owned by `landppt:landppt` and writable by its owner, but it will no longer use mode `0666`. Application directories and the non-root home directory will be writable by `landppt`; the virtual environment and Playwright browser files need only be readable and executable.

The health check and existing entrypoint will consequently execute as `landppt`. The entrypoint will stop attempting privileged permission repair and will instead perform a preflight check before starting the requested command.

## Docker Compose Permission Migration

Add `docker-permissions-init.sh` to the runtime image and add a `permissions-init` service to both `docker-compose.yml` and `docker-compose-dev.yaml`.

The service will:

- Use the same LandPPT image so the expected account and UID/GID are always available.
- Override the image user with `0:0` only for this one-shot task.
- Override the normal entrypoint with `docker-permissions-init.sh`.
- Mount only `.env` and the five LandPPT named volumes at dedicated paths below `/mnt/landppt`; it will not mount `/app` or the development source tree.
- Disable networking and container restart.
- Use a read-only root filesystem.
- Drop all Linux capabilities, then add only those required for ownership repair and target-identity verification: `CHOWN`, `FOWNER`, `DAC_OVERRIDE`, `SETUID`, and `SETGID`. The script uses the last two only to drop a validation child process to UID/GID `10001`; the long-lived containers receive none of these capabilities.

For each named volume, the script will look for a `.landppt-permissions-v1` marker. If absent, it will recursively set ownership to `10001:10001`, create the marker only after successful migration, and validate that UID/GID `10001` can write the volume. A present marker makes subsequent starts a fast validation path.

For the bind-mounted `.env`, the script will preserve the host-side owner, assign group `10001`, and grant group read/write access without granting access to other users. It will tolerate ownership operations that are unsupported by Docker Desktop file sharing only when an effective write check as UID/GID `10001` succeeds.

The web and worker services will depend on `permissions-init` with `condition: service_completed_successfully`, in addition to their existing database, cache, and object-storage dependencies. A failed migration therefore prevents either application process from starting.

## Kubernetes Security and PVC Migration

The Helm chart defaults will set the pod security context to:

```yaml
runAsNonRoot: true
runAsUser: 10001
runAsGroup: 10001
fsGroup: 10001
fsGroupChangePolicy: OnRootMismatch
seccompProfile:
  type: RuntimeDefault
```

The container security context will disallow privilege escalation and drop all capabilities. The web deployment and migration job already render the configurable context; the worker deployment will be updated to render it as well.

For supported POSIX PVC implementations, `fsGroup` makes existing volume contents group-writable by the LandPPT process. `OnRootMismatch` performs the recursive adjustment when the volume root does not match and avoids repeating it after the first successful mount. This is the automatic migration path for the repository's current Helm deployment.

The chart will keep these security-context objects configurable for storage-specific requirements. The numeric UID/GID must remain aligned with the image; using another identity is supported only with a custom image built with the same identity.

## Startup and Error Handling

The application entrypoint will continue to create required directories and use `exec` for the final command so signal behavior does not change. Before execution, it will verify:

- `/app/.env` is a regular, readable, writable file when present.
- The data, upload, report, cache, and library paths exist and are writable.
- The current effective UID is non-zero.

A failed check will identify the exact path and exit non-zero. The entrypoint will not attempt `chmod`, `chown`, copying, or replacement because the long-lived application container must not need elevated access.

The Compose migration script will also fail closed. It will not write a migration marker until recursive ownership and effective-identity validation have both succeeded. This allows a later start to retry a previously interrupted migration safely.

## Security Properties

- The shipped image is non-root even when used outside Compose or Helm.
- Long-lived web and worker containers have no root bootstrap phase.
- The Compose root helper is short-lived, networkless, capability-restricted, and cannot see the application source tree.
- Kubernetes enforces non-root execution independently of image metadata.
- `.env` is no longer world-writable.
- UID/GID stability prevents ownership changes caused by distribution account-allocation differences.

## Testing and Verification

Add focused regression tests under `tests/` that verify:

- The final Docker stage creates fixed UID/GID `10001`, sets the non-root home, declares `USER landppt`, and does not make `.env` world-writable.
- Both Compose files define the restricted initialization service with the expected mounts, capabilities, user override, and restart/network settings.
- Web and worker services wait for successful permission initialization.
- Helm defaults contain the fixed identity, `runAsNonRoot`, `fsGroup`, `OnRootMismatch`, and restricted container context.
- Web, worker, and migration templates render the security context.
- The migration script uses the version marker, validates target-identity access, and fails clearly.

Repository-level verification will run:

```text
uv run --extra dev pytest tests/test_container_security.py
uv run --extra dev pytest
docker compose config
docker compose -f docker-compose-dev.yaml config
helm lint helm/landppt
helm template landppt helm/landppt
trivy config --severity HIGH,CRITICAL --exit-code 1 .
```

When a Docker daemon is available, an isolated runtime test will:

1. Build the image.
2. Create test volumes containing root-owned files.
3. Start the Compose stack under an isolated project name.
4. Verify the initializer exits successfully and is idempotent.
5. Verify web and worker processes have effective UID `10001`.
6. Verify the application can write all persisted paths and passes its health check.

If the local environment lacks Docker, the handoff will identify this runtime test as not executed; the static Compose, Helm, pytest, and Trivy checks remain required when their tools are available.

## Rollout

On the first Compose startup after upgrade, `permissions-init` may take longer while it migrates existing files. Subsequent starts use the marker-based fast path. On the first Helm rollout, kubelet or the CSI driver may spend additional time applying `fsGroup` to existing PVC contents; `OnRootMismatch` prevents that cost on later mounts.

The GitHub security alert should close after the updated Dockerfile is scanned on the default branch. No alert dismissal or suppression is part of this change.

## Non-Goals

- Supporting automatic migration for arbitrary legacy `docker run` commands.
- Making the entire application root filesystem read-only.
- Refactoring application storage paths or configuration persistence.
- Changing database, cache, MinIO, or third-party image users.
- Dismissing or suppressing Trivy `DS-0002`.
