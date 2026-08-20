"""Runner de migrations minimalista: aplica os .sql de migrations/ em ordem
alfabetica, uma vez cada, registrando o que ja rodou em schema_migrations.

Sem dependencia de framework (Alembic etc.) porque o schema ainda e simples
e a evolucao dele acompanha fases do produto, nao migrações incrementais
finas de ORM. Reavaliar se isso comecar a doer.
"""

import sys
from pathlib import Path

import psycopg
import structlog

from app.config import get_settings

log = structlog.get_logger()

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def applied_versions(conn: psycopg.Connection) -> set[str]:
    conn.execute(
        """
        create table if not exists schema_migrations (
            version text primary key,
            applied_at timestamptz not null default now()
        )
        """
    )
    conn.commit()
    rows = conn.execute("select version from schema_migrations").fetchall()
    return {row[0] for row in rows}


def main() -> int:
    settings = get_settings()
    pending = sorted(p for p in MIGRATIONS_DIR.glob("*.sql"))
    if not pending:
        log.warning("nenhuma migration encontrada", dir=str(MIGRATIONS_DIR))
        return 0

    with psycopg.connect(settings.database_url) as conn:
        done = applied_versions(conn)
        for path in pending:
            if path.name in done:
                log.info("ja aplicada, pulando", migration=path.name)
                continue
            sql = path.read_text(encoding="utf-8")
            log.info("aplicando", migration=path.name)
            with conn.transaction():
                conn.execute(sql)
                conn.execute(
                    "insert into schema_migrations (version) values (%s)",
                    (path.name,),
                )
            log.info("aplicada", migration=path.name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
