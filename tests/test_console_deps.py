import pytest
from fastapi import HTTPException

from app.console.deps import checar_origin, estado_run_hoje
from app.console.queries import EstadoRun
from tests._fakes import FakeCursor


def test_estado_run_hoje_delega_para_carregar_estado_run():
    cur = FakeCursor(fetchone_results=[None])

    estado = estado_run_hoje(cur)

    assert estado == EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())


def test_checar_origin_recusa_ausencia_de_header():
    # Falha fechado (achado MEDIUM do security-reviewer, Fase 5c) - sem
    # Origin tambem e recusado, nao so uma origem estranha.
    with pytest.raises(HTTPException) as exc_info:
        checar_origin(None)
    assert exc_info.value.status_code == 403


def test_checar_origin_permite_origem_local():
    checar_origin("http://127.0.0.1:8000")  # nao levanta


def test_checar_origin_recusa_origem_estranha():
    with pytest.raises(HTTPException) as exc_info:
        checar_origin("http://evil.example.com")

    assert exc_info.value.status_code == 403
