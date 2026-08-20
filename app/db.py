"""Conexao com o Postgres via psycopg, thin wrapper sobre DATABASE_URL."""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg

from app.config import get_settings


@contextmanager
def get_connection() -> Iterator[psycopg.Connection]:
    settings = get_settings()
    with psycopg.connect(settings.database_url) as conn:
        yield conn
