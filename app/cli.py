"""
CLI for running ingest without starting the server.

Usage:
    uv run python -m app.cli sync --repo pallets/flask --since 2024-01-01 --until 2024-06-30
"""

import asyncio
from datetime import date

import typer

from app.config import get_settings
from app.db import build_engine, build_session_factory, create_tables
from app.ingest.service import IngestService
from app.logging_config import configure_logging

cli = typer.Typer(help="GitHub Insights API — CLI tools")


@cli.command()
def sync(
    repo: str = typer.Option(..., help="Repository in owner/name format"),
    since: str = typer.Option(..., help="Start date (YYYY-MM-DD)"),
    until: str = typer.Option(..., help="End date (YYYY-MM-DD)"),
) -> None:
    """Ingest a repository for a given date range."""
    asyncio.run(_sync(repo, date.fromisoformat(since), date.fromisoformat(until)))


async def _sync(repo: str, since: date, until: date) -> None:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)

    engine = build_engine(settings.database_url)
    session_factory = build_session_factory(engine)
    await create_tables(engine)

    async with session_factory() as session:
        service = IngestService(session, settings)
        run = await service.sync(repo, since, until)

    await engine.dispose()
    typer.echo(f"Done: status={run.status}, rows_ingested={run.rows_ingested}")


if __name__ == "__main__":
    cli()
