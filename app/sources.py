"""Acesso a sources, compartilhado entre coletores de palpites (Fase 2).

Toda fonte nova nasce em quarentena e ativa - sair da quarentena e
decisao manual do PM, nunca configuracao default (ver documento original,
"Regras de quarentena", e CLAUDE.md).
"""

import psycopg


def upsert_source(cur: psycopg.Cursor, nome: str, tipo: str, endpoint: str) -> str:
    cur.execute(
        """
        insert into sources (nome, tipo, endpoint, ativo, quarentena)
        values (%s, %s, %s, true, true)
        on conflict (nome) do update set endpoint = excluded.endpoint
        returning id
        """,
        (nome, tipo, endpoint),
    )
    return cur.fetchone()[0]
