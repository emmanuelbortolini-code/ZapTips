import pytest
from apscheduler.schedulers.background import BackgroundScheduler

import scripts.agendador as agendador
import scripts.backup as backup
import scripts.build_bets as build_bets
import scripts.build_master_ledger as build_master_ledger
import scripts.collect_results as collect_results
import scripts.gerar_fechamentos as gerar_fechamentos
import scripts.gerar_pagina_publica as gerar_pagina_publica
import scripts.gerar_resumo_semanal as gerar_resumo_semanal
import scripts.liquidar_picks as liquidar_picks
import scripts.run_pipeline as run_pipeline
from app.pipeline import ResultadoEtapa
from scripts.agendador import (
    _backup_diario,
    _coleta_resultados,
    _fechamento_diario,
    _liquidacao,
    _pipeline_diario,
    _resumo_semanal,
    _rodar_job,
    montar_scheduler,
)


def test_rodar_job_executa_a_funcao():
    chamadas = []
    _rodar_job("x", lambda: chamadas.append(1))
    assert chamadas == [1]


def test_rodar_job_isola_excecao_nunca_propaga():
    def explode():
        raise RuntimeError("falha de rede")

    # Nao deve levantar - excecao de um job nunca pode derrubar o
    # processo do agendador nem impedir outros jobs de rodarem.
    _rodar_job("x", explode)


def test_montar_scheduler_registra_os_6_jobs_esperados():
    sched = montar_scheduler()
    ids = {job.id for job in sched.get_jobs()}
    assert ids == {"pipeline_diario", "coleta_resultados", "liquidacao", "fechamento_diario", "backup_diario", "resumo_semanal"}


def test_montar_scheduler_aceita_background_scheduler():
    sched = montar_scheduler(BackgroundScheduler)
    ids = {job.id for job in sched.get_jobs()}
    assert isinstance(sched, BackgroundScheduler)
    assert ids == {"pipeline_diario", "coleta_resultados", "liquidacao", "fechamento_diario", "backup_diario", "resumo_semanal"}
    # montar_scheduler nunca chama start() (main() faz isso separado) -
    # sem thread rodando, nao ha nada pra desligar aqui.


def test_montar_scheduler_pipeline_diario_roda_as_6h():
    sched = montar_scheduler()
    job = sched.get_job("pipeline_diario")
    campos = {f.name: f for f in job.trigger.fields}
    assert str(campos["hour"]) == "6"
    assert str(campos["minute"]) == "0"


def test_montar_scheduler_fechamento_diario_roda_as_23h():
    sched = montar_scheduler()
    job = sched.get_job("fechamento_diario")
    campos = {f.name: f for f in job.trigger.fields}
    assert str(campos["hour"]) == "23"


def test_montar_scheduler_backup_roda_as_4h():
    sched = montar_scheduler()
    job = sched.get_job("backup_diario")
    campos = {f.name: f for f in job.trigger.fields}
    assert str(campos["hour"]) == "4"


def test_montar_scheduler_coleta_e_liquidacao_rodam_a_cada_30min():
    sched = montar_scheduler()
    for job_id in ("coleta_resultados", "liquidacao"):
        job = sched.get_job(job_id)
        campos = {f.name: f for f in job.trigger.fields}
        assert str(campos["minute"]) == "*/30"


def test_montar_scheduler_resumo_semanal_roda_as_5h_so_na_segunda():
    sched = montar_scheduler()
    job = sched.get_job("resumo_semanal")
    campos = {f.name: f for f in job.trigger.fields}
    assert str(campos["hour"]) == "5"
    assert str(campos["minute"]) == "0"
    assert str(campos["day_of_week"]) == "mon"


# --- cada wrapper chama a funcao certa (achado: um typo aqui so' seria pego em runtime) --


def test_pipeline_diario_chama_run_pipeline_executar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(run_pipeline, "executar", lambda: chamadas.append(1) or ResultadoEtapa(status="ok"))
    _pipeline_diario()
    assert chamadas == [1]


def test_coleta_resultados_chama_collect_results_executar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(collect_results, "executar", lambda: chamadas.append(1) or ResultadoEtapa(status="ok"))
    _coleta_resultados()
    assert chamadas == [1]


def test_liquidacao_chama_liquidar_picks_executar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(liquidar_picks, "executar", lambda: chamadas.append(1) or ResultadoEtapa(status="ok"))
    _liquidacao()
    assert chamadas == [1]


def test_fechamento_diario_chama_master_ledger_bets_fechamentos_e_pagina_publica_em_ordem(monkeypatch):
    ordem = []
    monkeypatch.setattr(build_master_ledger, "executar", lambda: ordem.append("master_ledger") or 0)
    monkeypatch.setattr(build_bets, "executar", lambda: ordem.append("bets") or {})
    monkeypatch.setattr(gerar_fechamentos, "executar", lambda: ordem.append("fechamentos") or ResultadoEtapa(status="ok"))
    monkeypatch.setattr(gerar_pagina_publica, "executar", lambda: ordem.append("pagina_publica") or ResultadoEtapa(status="ok"))

    _fechamento_diario()

    assert ordem == ["master_ledger", "bets", "fechamentos", "pagina_publica"]


def test_backup_diario_chama_backup_executar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(backup, "executar", lambda: chamadas.append(1) or ResultadoEtapa(status="ok"))
    _backup_diario()
    assert chamadas == [1]


def test_resumo_semanal_chama_gerar_resumo_semanal_executar(monkeypatch):
    chamadas = []
    monkeypatch.setattr(gerar_resumo_semanal, "executar", lambda: chamadas.append(1) or ResultadoEtapa(status="ok"))
    _resumo_semanal()
    assert chamadas == [1]
