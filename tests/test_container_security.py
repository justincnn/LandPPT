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
    services = compose_text.split("\nservices:\n", 1)[1]
    return services.split("  permissions-init:\n", 1)[1].split(
        "\n  landppt:\n", 1
    )[0]


def compose_service(
    compose_text: str, service_name: str, next_service_name: str
) -> str:
    services = compose_text.split("\nservices:\n", 1)[1]
    return services.split(f"  {service_name}:\n", 1)[1].split(
        f"\n  {next_service_name}:\n", 1
    )[0]


def compose_sequence(service_text: str, key: str, next_key: str) -> list[str]:
    sequence = service_text.split(f"\n    {key}:\n", 1)[1].split(
        f"\n    {next_key}:", 1
    )[0]
    return [
        line.removeprefix("      - ")
        for line in sequence.splitlines()
        if line.startswith("      - ")
    ]


def compose_dependency_anchor(compose_text: str) -> str:
    return compose_text.split(
        "x-landppt-depends-on: &landppt-depends-on", 1
    )[1].split("\n\nservices:", 1)[0]


@pytest.mark.parametrize("compose_path", ["docker-compose.yml", "docker-compose-dev.yaml"])
def test_compose_migrates_permissions_before_app_start(compose_path: str):
    compose_text = read_repo_file(compose_path)
    init_service = compose_init_service(compose_text)
    dependencies = compose_dependency_anchor(compose_text)
    landppt_service = compose_service(compose_text, "landppt", "worker")
    worker_service = compose_service(compose_text, "worker", "postgres")

    assert 'user: "0:0"' in init_service
    assert 'entrypoint: ["/usr/local/bin/docker-permissions-init.sh"]' in init_service
    assert 'network_mode: "none"' in init_service
    assert "read_only: true" in init_service
    assert 'restart: "no"' in init_service
    assert compose_sequence(init_service, "cap_drop", "cap_add") == ["ALL"]
    assert compose_sequence(init_service, "cap_add", "security_opt") == [
        "CHOWN",
        "FOWNER",
        "DAC_OVERRIDE",
        "SETUID",
        "SETGID",
    ]
    assert "no-new-privileges:true" in init_service

    assert compose_sequence(init_service, "volumes", "network_mode") == [
        "${LANDPPT_ENV_FILE:-./.env}:/mnt/landppt/env/.env",
        "landppt_data:/mnt/landppt/data",
        "landppt_uploads:/mnt/landppt/uploads",
        "landppt_reports:/mnt/landppt/reports",
        "landppt_cache:/mnt/landppt/cache",
        "landppt_lib:/mnt/landppt/lib",
    ]

    assert "/app" not in init_service
    assert "docker.sock" not in init_service
    assert "/var/run/docker.sock" not in init_service
    assert "${LANDPPT_ENV_FILE:-./.env}:/app/.env" in compose_text
    assert "permissions-init:" in dependencies
    assert "condition: service_completed_successfully" in dependencies
    assert "depends_on: *landppt-depends-on" in landppt_service
    assert "depends_on: *landppt-depends-on" in worker_service


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


def test_permission_migration_marker_is_safe_and_keeps_fast_path():
    script = read_repo_file("docker-permissions-init.sh")

    assert "marker_state()" in script
    assert "create_marker()" in script
    assert "os.O_PATH" in script
    assert "os.O_NOFOLLOW" in script
    assert "os.O_EXCL" in script
    assert "os.fstat(" in script
    assert "stat.S_ISREG(" in script
    assert ".st_uid != uid" in script
    assert ".st_gid != gid" in script
    assert "stat.S_IMODE(" in script
    assert "!= 0o600" in script
    assert "os.fchown(" in script
    assert "os.fchmod(" in script
    assert '[ -f "$marker_path" ]' not in script
    assert ': > "$marker_path"' not in script
    assert script.count('chown -R "${TARGET_UID}:${TARGET_GID}"') == 1
    assert "Migration marker found for ${volume_path}; validating" in script
