"""Agendador (Fase 7) - processo unico de longa duracao que dispara os
jobs do produto em horario fixo (Brasilia), via APScheduler. Roda
`uv run python -m scripts.agendador` e fica no ar - nao e' um comando
que termina, e' o processo de producao (mesmo principio de "Postgres e
um processo so resolvem", spec "Escala definida": nada de fila
distribuida, worker pool ou infraestrutura acima do necessario pra
200 contatos).

Cada job so chama a mesma funcao executar() ja testada do script
correspondente - o agendador nao duplica nenhuma logica de negocio, so
decide QUANDO rodar. Toda excecao de um job fica isolada (nunca derruba
o processo nem afeta outro job agendado) - mesmo principio de
isolamento ja usado em app.pipeline.avancar_etapas e
scripts.run_pipeline._rodar_subetapa.

Horarios (spec, secao "Fase 7: Operacao"):
- 06:00: pipeline diario (fixtures->coleta->extracao->matching->odds->slate).
  Ate 09:00 (sessao de envio) sobra 3h pro operador curar/aprovar o
  slate com calma, ou reexecutar uma etapa degradada.
- a cada 30min: coleta de resultados + liquidacao - "ambos posteriores
  ao jogo e sem dependencia do slate" (spec), por isso independentes do
  job das 06:00.
- 23:00: fechamento do dia - master_ledger -> bets -> mensagens de
  fechamento -> pagina publica de performance, nessa ordem (os 3
  primeiros dependem do anterior; a pagina so' depende do master_ledger,
  roda por ultimo so' porque este job trata os 4 como "fechar o dia").
- 05:00, so as segundas: resumo semanal da semana anterior (segunda a
  domingo) - spec: "resumo semanal na segunda-feira... entra na mesma
  fila do console e sai na sessao do dia seguinte". Antes do pipeline
  das 06:00 (mesma folga de proposito que o backup das 04:00 tem em
  relacao ao pipeline), pra a mensagem ja estar pronta quando a sessao
  de envio das 9h abrir.
- 04:00: backup diario do Postgres, antes do pipeline das 06:00 comecar
  a escrever.

Uso:
    uv run python -m scripts.agendador
"""

import sys
from typing import Callable

import structlog
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import scripts.backup as backup
import scripts.build_bets as build_bets
import scripts.build_master_ledger as build_master_ledger
import scripts.collect_results as collect_results
import scripts.gerar_fechamentos as gerar_fechamentos
import scripts.gerar_pagina_publica as gerar_pagina_publica
import scripts.gerar_resumo_semanal as gerar_resumo_semanal
import scripts.liquidar_picks as liquidar_picks
import scripts.run_pipeline as run_pipeline

log = structlog.get_logger()

FUSO = "America/Sao_Paulo"


def _rodar_job(nome: str, fn: Callable[[], None]) -> None:
    # log.info de inicio DENTRO do try (achado LOW do code-reviewer): se
    # o proprio log falhasse (processor customizado quebrado, pipe de
    # stdout fechado), a excecao escaparia deste isolamento antes de
    # fn() sequer rodar - improvavel na pratica, mas gratis de fechar.
    try:
        log.info("job_iniciado", job=nome)
        fn()
        log.info("job_concluido", job=nome)
    except Exception:
        log.exception("job_falhou", job=nome)


def _pipeline_diario() -> None:
    resultado = run_pipeline.executar()
    log.info("pipeline_diario_resultado", status=resultado.status)


def _coleta_resultados() -> None:
    resultado = collect_results.executar()
    log.info("coleta_resultados_resultado", status=resultado.status, fechadas=resultado.itens_ok)


def _liquidacao() -> None:
    resultado = liquidar_picks.executar()
    log.info("liquidacao_resultado", status=resultado.status, liquidados=resultado.itens_ok)


def _fechamento_diario() -> None:
    total_ledger = build_master_ledger.executar()
    apostas_por_usuario = build_bets.executar()
    resultado_fechamento = gerar_fechamentos.executar()
    # Pagina publica por ultimo (spec: "regerada ao fim da liquidacao
    # diaria") - depende so' de master_ledger, ja fresco pelo primeiro
    # passo acima; roda depois de bets/fechamentos so' porque este job
    # trata os 3 como "fechar o dia", nunca porque a pagina precisa
    # deles.
    resultado_pagina = gerar_pagina_publica.executar()
    log.info(
        "fechamento_diario_resultado",
        master_ledger_entradas=total_ledger,
        usuarios_com_extrato=len(apostas_por_usuario),
        fechamentos_gerados=resultado_fechamento.itens_ok,
        pagina_publica_status=resultado_pagina.status,
    )


def _backup_diario() -> None:
    resultado = backup.executar()
    log.info("backup_resultado", status=resultado.status, detalhe=resultado.detalhe)


def _resumo_semanal() -> None:
    resultado = gerar_resumo_semanal.executar()
    log.info("resumo_semanal_resultado", status=resultado.status, gerados=resultado.itens_ok)


def montar_scheduler(scheduler_cls=None) -> BlockingScheduler | BackgroundScheduler:
    if scheduler_cls is None:
        scheduler_cls = BlockingScheduler
    sched = scheduler_cls(timezone=FUSO)

    sched.add_job(
        lambda: _rodar_job("pipeline_diario", _pipeline_diario),
        CronTrigger(hour=6, minute=0, timezone=FUSO), id="pipeline_diario",
    )
    sched.add_job(
        lambda: _rodar_job("coleta_resultados", _coleta_resultados),
        CronTrigger(minute="*/30", timezone=FUSO), id="coleta_resultados",
    )
    sched.add_job(
        lambda: _rodar_job("liquidacao", _liquidacao),
        CronTrigger(minute="*/30", timezone=FUSO), id="liquidacao",
    )
    sched.add_job(
        lambda: _rodar_job("fechamento_diario", _fechamento_diario),
        CronTrigger(hour=23, minute=0, timezone=FUSO), id="fechamento_diario",
    )
    sched.add_job(
        lambda: _rodar_job("backup_diario", _backup_diario),
        CronTrigger(hour=4, minute=0, timezone=FUSO), id="backup_diario",
    )
    sched.add_job(
        lambda: _rodar_job("resumo_semanal", _resumo_semanal),
        CronTrigger(day_of_week="mon", hour=5, minute=0, timezone=FUSO), id="resumo_semanal",
    )

    return sched


def main() -> int:
    from app.config import get_settings

    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    sched = montar_scheduler()
    log.info("agendador_iniciado", fuso=FUSO, jobs=[job.id for job in sched.get_jobs()])
    try:
        sched.start()
    except (KeyboardInterrupt, SystemExit):
        log.info("agendador_encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
