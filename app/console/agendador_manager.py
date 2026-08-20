"""Gerenciador de background tasks do console (Fase 7+Controle) -
controla o APScheduler (em BackgroundScheduler dentro do processo do
console) e executa operacoes manuais (pipeline, liquidacao) em threads
separadas, com locks por tarefa pra evitar concorrencia.

Singleton por processo: `obter_manager()` devolve a mesma instancia
enquanto o processo viver. `reset_manager()` existe so pra testes -
desliga o scheduler, espera as threads terminarem e apaga o estado.

Cada tarefa manual tem status proprio (ocioso/rodando/ok/falhou),
ultimo resultado e ultimo erro. A rota `/controle` le esse estado e
mostra na tela; quando o operador clica "Rodar", a rota submete a
funcao pro ThreadPoolExecutor e redireciona de volta.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable

import structlog

from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Excecoes controladas
# ---------------------------------------------------------------------------

class ExecucaoConcorrente(Exception):
    """Tarefa ja esta rodando - nao duplicar."""


class JobDesconhecido(Exception):
    """job_id nao esta na allowlist de jobs conhecidos."""


# Allowlist de jobs que podem ser disparados manualmente pelo console.
JOBS_PERMITIDOS: frozenset[str] = frozenset({
    "pipeline_diario",
    "coleta_resultados",
    "liquidacao",
    "fechamento_diario",
    "backup_diario",
})


# ---------------------------------------------------------------------------
# Status de uma tarefa manual
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatusTarefa:
    nome: str
    status: str  # ocioso | rodando | ok | falhou
    ultima_execucao: datetime | None
    ultimo_resultado: ResultadoEtapa | None
    ultimo_erro: str | None


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------

class _TaskManager:
    """Estado compartilhado entre a rota e as threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._scheduler = None  # BackgroundScheduler | None
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="zaptips-controle")
        self._tarefas: dict[str, dict[str, Any]] = {
            "pipeline": {"status": "ocioso", "ultima_execucao": None, "ultimo_resultado": None, "ultimo_erro": None},
            "liquidacao": {"status": "ocioso", "ultima_execucao": None, "ultimo_resultado": None, "ultimo_erro": None},
        }

    # ------------------------------------------------------------------
    # Scheduler
    # ------------------------------------------------------------------

    def iniciar_scheduler(self) -> None:
        with self._lock:
            if self._scheduler is not None and self._scheduler.running:
                log.info("agendador_ja_ativo")
                return
            from scripts.agendador import montar_scheduler
            from apscheduler.schedulers.background import BackgroundScheduler

            self._scheduler = montar_scheduler(BackgroundScheduler)
            self._scheduler.start()
            log.info("agendador_iniciado_console", jobs=[j.id for j in self._scheduler.get_jobs()])

    def parar_scheduler(self) -> None:
        with self._lock:
            if self._scheduler is None or not self._scheduler.running:
                log.info("agendador_ja_parado")
                return
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            log.info("agendador_parado_console")

    def scheduler_esta_rodando(self) -> bool:
        return self._scheduler is not None and self._scheduler.running

    def listar_jobs(self) -> list[dict[str, str]]:
        if self._scheduler is None:
            return []
        resultado = []
        for job in self._scheduler.get_jobs():
            proximo = job.next_run_time
            resultado.append({
                "id": job.id,
                "proximo_disparo": proximo.strftime("%H:%M:%S") if proximo else "aguardando",
                "trigger": str(job.trigger),
            })
        return resultado

    def disparar_job(self, job_id: str) -> None:
        if job_id not in JOBS_PERMITIDOS:
            raise JobDesconhecido(f"Job '{job_id}' nao existe ou nao pode ser disparado manualmente.")
        if self._scheduler is None or not self._scheduler.running:
            raise RuntimeError("Agendador nao esta ativo - inicie-o antes de disparar jobs.")
        job = self._scheduler.get_job(job_id)
        if job is None:
            raise JobDesconhecido(f"Job '{job_id}' nao encontrado no scheduler.")
        self._scheduler.modify_job(job_id, next_run_time=datetime.now(timezone.utc))
        log.info("job_disparado_manualmente", job_id=job_id)

    # ------------------------------------------------------------------
    # Tarefas manuais (pipeline, liquidacao)
    # ------------------------------------------------------------------

    def status_tarefa(self, nome: str) -> StatusTarefa:
        t = self._tarefas[nome]
        return StatusTarefa(
            nome=nome,
            status=t["status"],
            ultima_execucao=t["ultima_execucao"],
            ultimo_resultado=t["ultimo_resultado"],
            ultimo_erro=t["ultimo_erro"],
        )

    def executar_em_background(self, nome: str, fn: Callable[[], Any]) -> None:
        with self._lock:
            atual = self._tarefas[nome]
            if atual["status"] == "rodando":
                raise ExecucaoConcorrente(f"Tarefa '{nome}' ja esta em andamento.")
            atual["status"] = "rodando"
            atual["ultimo_erro"] = None

        def _wrapper() -> None:
            try:
                resultado = fn()
                with self._lock:
                    self._tarefas[nome]["status"] = "ok"
                    self._tarefas[nome]["ultimo_resultado"] = resultado
                    self._tarefas[nome]["ultima_execucao"] = datetime.now(timezone.utc)
                log.info("tarefa_concluida", tarefa=nome, status="ok")
            except Exception as exc:
                with self._lock:
                    self._tarefas[nome]["status"] = "falhou"
                    self._tarefas[nome]["ultimo_erro"] = type(exc).__name__
                    self._tarefas[nome]["ultima_execucao"] = datetime.now(timezone.utc)
                log.exception("tarefa_falhou", tarefa=nome)

        self._executor.submit(_wrapper)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: _TaskManager | None = None
_init_lock = threading.Lock()


def obter_manager() -> _TaskManager:
    global _instance  # noqa: PLW0603
    if _instance is None:
        with _init_lock:
            if _instance is None:
                _instance = _TaskManager()
    return _instance


def reset_manager() -> None:
    """Desliga scheduler, espera threads e apaga o singleton. So pra testes."""
    global _instance  # noqa: PLW0603
    with _init_lock:
        if _instance is not None:
            try:
                _instance.parar_scheduler()
            except Exception:
                pass
            _instance._executor.shutdown(wait=True)
            _instance = None
