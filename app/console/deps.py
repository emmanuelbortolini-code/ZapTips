"""Dependencias FastAPI do console (Fase 5c) - adaptador fino sobre
app.db.get_connection (um @contextmanager, nao desenhado pra DI). Rotas
de leitura pedem um cursor (get_cursor); rotas de escrita pedem a
conexao inteira (get_conexao) pra controlar o commit explicitamente, do
mesmo jeito que todo scripts/*.py ja faz - sem semantica nova de commit
implicito pra alguem aprender.

Toda rota e `def`, nunca `async def`: psycopg e sincrono, e uma rota
async fazendo I/O bloqueante travaria o event loop inteiro (regra do
projeto pra FastAPI - ver ~/.claude/rules/ecc/python/fastapi.md).
"""

from collections.abc import Iterator

import psycopg
from fastapi import Depends, Header, HTTPException

from app.console.queries import EstadoRun, carregar_estado_run
from app.db import get_connection
from app.pipeline import data_operacional

# Sem autenticacao e proposital ("roda so na maquina local do PM, sem
# deploy" - CLAUDE.md, "Ambiente de execucao"), mas uma requisicao POST
# vinda de outra aba do navegador (CSRF classico contra apps locais sem
# auth) ainda pode ser recusada de graca checando Origin - aprovar um
# slate e uma acao com efeito real (vai pros assinantes).
ORIGENS_PERMITIDAS = frozenset({"http://127.0.0.1:8000", "http://localhost:8000"})


def get_cursor() -> Iterator[psycopg.Cursor]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            yield cur


def get_conexao() -> Iterator[psycopg.Connection]:
    with get_connection() as conn:
        yield conn


def estado_run_hoje(cur: psycopg.Cursor = Depends(get_cursor)) -> EstadoRun:
    return carregar_estado_run(cur, data_operacional())


def checar_origin(origin: str | None = Header(default=None)) -> None:
    # Falha fechado (achado MEDIUM do security-reviewer, Fase 5c):
    # ausencia de Origin tambem e recusada, nao so uma origem estranha.
    # O unico cliente legitimo deste console e um navegador moderno
    # batendo em 127.0.0.1:8000/localhost:8000, que sempre envia Origin
    # num POST - "sem header" nao e o caminho comum, e e exatamente o
    # que uma pagina hostil em outra aba tentaria explorar se o
    # servidor tratasse a ausencia como permissao.
    if origin not in ORIGENS_PERMITIDAS:
        raise HTTPException(status_code=403, detail="origem nao permitida ou ausente")
