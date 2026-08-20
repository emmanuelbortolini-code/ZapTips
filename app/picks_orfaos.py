"""Registro de picks fora do fluxo normal - tabela picks_orfaos,
compartilhada entre dois usos distintos desde a Fase 5a (migration 0016
separa por `tipo`, unique (pick_id, tipo)):

- `excluido`: pick descartado da curadoria (sem_odd, odd abaixo do piso,
  conflito) - usado por scripts/resolve_odds.py e scripts/build_slate.py
  desde a Fase 4, sem contador de retentativa (motivo nao muda com o
  tempo, so registra o porque).
- `sem_fixture`: pick cujos times resolveram mas a fixture ainda nao
  existe (fonte publicou antes do job de fixtures cobrir a data) -
  usado por scripts/link_picks.py (Fase 5a), com contador de tentativas
  de rematching a cada run que traz fixture nova. Depois de
  MAX_TENTATIVAS_MATCHING sem sucesso, escala pra revisao manual
  (especificacao da Fase 5, "Palpites orfaos", linha 1023)."""

import psycopg

TIPO_EXCLUIDO = "excluido"
TIPO_SEM_FIXTURE = "sem_fixture"

MAX_TENTATIVAS_MATCHING = 5


def upsert_pick_orfao(cur: psycopg.Cursor, pick_id: str, motivo: str, tipo: str = TIPO_EXCLUIDO) -> int:
    cur.execute(
        """
        insert into picks_orfaos (pick_id, tipo, motivo, tentativas, ultima_tentativa_em)
        values (%s::uuid, %s, %s, 1, now())
        on conflict (pick_id, tipo) do update set
            motivo = excluded.motivo,
            tentativas = picks_orfaos.tentativas + 1,
            ultima_tentativa_em = now()
        returning tentativas
        """,
        (pick_id, tipo, motivo),
    )
    return cur.fetchone()[0]


def limpar_pick_orfao(cur: psycopg.Cursor, pick_id: str, tipo: str) -> None:
    cur.execute("delete from picks_orfaos where pick_id = %s::uuid and tipo = %s", (pick_id, tipo))


def deve_escalar_para_revisao(tentativas: int) -> bool:
    return tentativas >= MAX_TENTATIVAS_MATCHING
