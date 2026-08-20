from datetime import date

from app.pipeline import ETAPAS, ResultadoEtapa
from app.pipeline_runs import (
    abrir_run,
    carregar_resultados,
    fechar_etapa,
    fechar_run,
    iniciar_etapa,
    resetar_etapas_travadas,
)
from tests._fakes import FakeCursor


def _etapa(nome: str):
    return next(e for e in ETAPAS if e.nome == nome)


def test_abrir_run_reaproveita_run_existente_do_dia():
    cur = FakeCursor(fetchone_results=[("run-existente",)])

    run_id, criado_agora = abrir_run(cur, date(2026, 8, 11))

    assert run_id == "run-existente"
    assert criado_agora is False
    assert len(cur.queries) == 1
    sql, params = cur.queries[0]
    assert "select id from pipeline_runs where data_referencia" in sql
    assert params == (date(2026, 8, 11),)


def test_abrir_run_cria_quando_nao_existe():
    cur = FakeCursor(fetchone_results=[None, ("run-novo",)])

    run_id, criado_agora = abrir_run(cur, date(2026, 8, 11))

    assert run_id == "run-novo"
    assert criado_agora is True
    sql_insert, params_insert = cur.queries[1]
    assert "insert into pipeline_runs" in sql_insert
    assert "status" in sql_insert
    assert params_insert == (date(2026, 8, 11),)


def test_resetar_etapas_travadas_filtra_status_rodando():
    cur = FakeCursor(fetchall_results=[[("odds",), ("slate",)]])

    travadas = resetar_etapas_travadas(cur, "run-1")

    assert travadas == ["odds", "slate"]
    sql, params = cur.queries[0]
    assert "update pipeline_stages set status = 'pendente'" in sql
    assert "status = 'rodando'" in sql
    assert params == ("run-1",)


def test_iniciar_etapa_faz_upsert_por_run_e_etapa():
    cur = FakeCursor()

    iniciar_etapa(cur, "run-1", _etapa("fixtures"))

    sql, params = cur.queries[0]
    assert "on conflict (run_id, etapa)" in sql
    assert "status = 'rodando'" in sql
    assert params == ("run-1", "fixtures", 1)
    sql_run, params_run = cur.queries[1]
    assert "update pipeline_runs set etapa_atual" in sql_run
    assert params_run == ("fixtures", "run-1")


def test_fechar_etapa_grava_contadores_e_detalhe():
    cur = FakeCursor()
    resultado = ResultadoEtapa(status="degradado", itens_ok=3, itens_erro=1, detalhe={"motivo": "x"})

    fechar_etapa(cur, "run-1", _etapa("coleta"), resultado)

    sql, params = cur.queries[0]
    assert "update pipeline_stages set" in sql
    assert "itens_ok" in sql and "itens_erro" in sql and "detalhe_json" in sql
    assert params[0] == "degradado"
    assert params[1] == 3
    assert params[2] == 1
    assert dict(params[3].obj) == {"motivo": "x"}
    assert params[4] == "run-1"
    assert params[5] == "coleta"


def test_fechar_run_grava_status_e_etapa_atual():
    cur = FakeCursor()

    fechar_run(cur, "run-1", "degradado", "odds")

    sql, params = cur.queries[0]
    assert "update pipeline_runs set" in sql
    assert "finalizado_em = now()" in sql
    assert params == ("degradado", "odds", "run-1")


def test_carregar_resultados_so_inclui_etapas_fechadas():
    cur = FakeCursor(
        fetchall_results=[
            [
                ("fixtures", "ok", 42, 0, None),
                ("coleta", "degradado", 9, 1, {"subetapas": {}}),
                ("extracao", "rodando", 0, 0, None),
                ("matching", "pendente", 0, 0, None),
            ]
        ]
    )

    resultados = carregar_resultados(cur, "run-1")

    assert set(resultados.keys()) == {"fixtures", "coleta"}
    assert resultados["fixtures"] == ResultadoEtapa(status="ok", itens_ok=42, itens_erro=0, detalhe={})
    assert resultados["coleta"] == ResultadoEtapa(status="degradado", itens_ok=9, itens_erro=1, detalhe={"subetapas": {}})
