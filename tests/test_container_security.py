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
