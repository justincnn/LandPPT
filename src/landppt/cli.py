"""Operational CLI commands for LandPPT deployments."""

from __future__ import annotations

import asyncio
import logging
import sys

import click

from .auth.auth_service import init_default_admin
from .database.create_default_template import ensure_default_templates_exist
from .database.database import SessionLocal, close_db, init_db
from .database.migrations import migration_manager


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def _migrate() -> bool:
    await init_db(bootstrap_admin=False)
    return await migration_manager.migrate_up()


async def _bootstrap_default_templates() -> int:
    template_ids = await ensure_default_templates_exist()
    return len(template_ids or [])


def _bootstrap_admin() -> None:
    db = SessionLocal()
    try:
        init_default_admin(db)
    finally:
        db.close()


async def _run_with_db_close(coro):
    try:
        return await coro
    finally:
        await close_db()


def _run_async(coro):
    return asyncio.run(_run_with_db_close(coro))


@click.group()
def cli() -> None:
    """Run LandPPT operational commands."""


@cli.command("migrate")
def migrate() -> None:
    """Initialize database tables and apply pending migrations."""
    ok = _run_async(_migrate())
    if not ok:
        raise click.ClickException("Database migration failed")
    click.echo("Database migration completed")


@cli.command("bootstrap-default-templates")
def bootstrap_default_templates() -> None:
    """Create default templates when none exist."""
    count = _run_async(_bootstrap_default_templates())
    click.echo(f"Default template bootstrap completed: {count} available")


@cli.command("bootstrap-admin")
def bootstrap_admin() -> None:
    """Create the initial admin user when bootstrap is enabled and no users exist."""
    _bootstrap_admin()
    click.echo("Admin bootstrap completed")


@cli.command("migrate-and-bootstrap")
def migrate_and_bootstrap() -> None:
    """Run migrations, then bootstrap templates and the optional initial admin."""
    ok = _run_async(_migrate())
    if not ok:
        raise click.ClickException("Database migration failed")
    count = _run_async(_bootstrap_default_templates())
    _bootstrap_admin()
    click.echo(f"Migration and bootstrap completed: {count} templates available")


@cli.command("worker")
@click.option("--queue", "queue_name", default=None, help="Queue name to consume. Defaults to TASK_QUEUE_NAME.")
def worker(queue_name: str | None = None) -> None:
    """Run a queued task worker process."""
    from .tasks.worker import run_worker

    _run_async(run_worker(queue_name=queue_name))


def main() -> None:
    cli(prog_name="landppt")


if __name__ == "__main__":
    sys.exit(main())
