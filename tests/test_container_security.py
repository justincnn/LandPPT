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
