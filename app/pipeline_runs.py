"""Acesso a pipeline_runs/pipeline_stages (Fase 5a). Sem logica de
transicao aqui - so leitura/escrita das linhas que app/pipeline.py (puro)
consome e produz. Mesmo split ja usado em app/picks_orfaos.py.

`abrir_run` usa select-entao-insert sem lock explicito, mesmo padrao ja
documentado em scripts/build_slate.py (`criar_ou_reaproveitar_slate`):
a arquitetura do projeto ja exclui execucao concorrente ("roda so na
maquina local do PM... scheduler em processo unico", CLAUDE.md).

`resetar_etapas_travadas` assume a mesma garantia de processo unico: uma
etapa presa em 'rodando' so pode ser sobra de uma execucao anterior que
foi encerrada abruptamente (crash, Ctrl+C), nunca uma execucao
concorrente de verdade em andamento."""

from datetime import date

import psycopg
from psycopg.types.json import Jsonb

from app.pipeline import EtapaSpec, ResultadoEtapa, StatusRun


def abrir_run(cur: psycopg.Cursor, data_referencia: date) -> tuple[str, bool]:
    cur.execute("select id from pipeline_runs where data_referencia = %s", (data_referencia,))
    row = cur.fetchone()
    if row is not None:
        return str(row[0]), False

    cur.execute(
        "insert into pipeline_runs (data_referencia, status, iniciado_em) values (%s, 'rodando', now()) returning id",
        (data_referencia,),
    )
    return str(cur.fetchone()[0]), True


def resetar_etapas_travadas(cur: psycopg.Cursor, run_id: str) -> list[str]:
    cur.execute(
        "update pipeline_stages set status = 'pendente' where run_id = %s::uuid and status = 'rodando' returning etapa",
        (run_id,),
    )
    return [row[0] for row in cur.fetchall()]


def carregar_resultados(cur: psycopg.Cursor, run_id: str) -> dict[str, ResultadoEtapa]:
    cur.execute(
        "select etapa, status, itens_ok, itens_erro, detalhe_json from pipeline_stages where run_id = %s::uuid",
        (run_id,),
    )
    resultados: dict[str, ResultadoEtapa] = {}
    for etapa, status, itens_ok, itens_erro, detalhe_json in cur.fetchall():
        if status not in ("ok", "degradado", "falhou"):
            continue
        resultados[etapa] = ResultadoEtapa(status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe_json or {})
    return resultados


def iniciar_etapa(cur: psycopg.Cursor, run_id: str, etapa: EtapaSpec) -> None:
    cur.execute(
        """
        insert into pipeline_stages (run_id, etapa, ordem, status, iniciado_em)
        values (%s::uuid, %s, %s, 'rodando', now())
        on conflict (run_id, etapa) do update set
            status = 'rodando',
            iniciado_em = now(),
            finalizado_em = null
        """,
        (run_id, etapa.nome, etapa.ordem),
    )
    cur.execute("update pipeline_runs set etapa_atual = %s where id = %s::uuid", (etapa.nome, run_id))


def fechar_etapa(cur: psycopg.Cursor, run_id: str, etapa: EtapaSpec, resultado: ResultadoEtapa) -> None:
    cur.execute(
        """
        update pipeline_stages set
            status = %s, itens_ok = %s, itens_erro = %s, detalhe_json = %s, finalizado_em = now()
        where run_id = %s::uuid and etapa = %s
        """,
        (resultado.status, resultado.itens_ok, resultado.itens_erro, Jsonb(dict(resultado.detalhe)), run_id, etapa.nome),
    )


def fechar_run(cur: psycopg.Cursor, run_id: str, status: StatusRun, etapa_atual: str | None) -> None:
    cur.execute(
        "update pipeline_runs set status = %s, etapa_atual = %s, finalizado_em = now() where id = %s::uuid",
        (status, etapa_atual, run_id),
    )
