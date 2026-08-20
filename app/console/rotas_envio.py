"""Rota da aba Envio (Fase 5d) - so abre depois do slate de hoje
aprovado (app.console.rules.avaliar_acesso_envio). Modo sessao (Fase
5d-D): fluxo guiado que apresenta os assinantes um por vez, em ordem
justa e rotativa entre dias (app.messages_generator.ordem_da_sessao)."""

from datetime import datetime, timezone

import psycopg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.console.acoes import encerrar_sessao, iniciar_sessao, marcar_enviada, pausar_sessao, pular, retomar_sessao
from app.console.deps import checar_origin, estado_run_hoje, get_conexao, get_cursor
from app.console.queries import (
    EstadoRun,
    SessaoEnvio,
    buscar_sessao_aberta,
    contadores_do_dia,
    fila_envio,
    resumo_do_dia,
    universo_da_sessao,
)
from app.console.rules import (
    avaliar_acesso_envio,
    avaliar_acesso_sessao,
    excede_limite_caracteres,
    montar_link_whatsapp,
    montar_paradas,
    montar_resumo,
    parada_atual,
    progresso,
)
from app.daily_slates import buscar_slate_atual
from app.messages_generator import expirar_mensagens_vencidas
from app.pipeline import FUSO_OPERACIONAL, data_operacional

router = APIRouter()


def _mensagem_para_exibicao(msg) -> dict:
    # kickoff_utc/time_casa/time_fora sao None pra tipo='resumo_semanal'
    # (Fase 6e) - mensagem agregada da semana, sem partida associada.
    # `rotulo` da o texto que o card mostra no lugar de "X x Y".
    return {
        **msg.__dict__,
        "rotulo": f"{msg.time_casa} x {msg.time_fora}" if msg.fixture_id is not None else "Resumo semanal",
        "kickoff_local": msg.kickoff_utc.astimezone(FUSO_OPERACIONAL) if msg.kickoff_utc is not None else None,
        "link_whatsapp": montar_link_whatsapp(msg.telefone_e164, msg.corpo_renderizado),
        "excede_limite": excede_limite_caracteres(msg.corpo_renderizado),
    }


def _agrupar_por_assinante(mensagens: list[dict]) -> list[dict]:
    por_usuario: dict[str, dict] = {}
    for msg in mensagens:
        grupo = por_usuario.setdefault(
            msg["user_id"], {"user_id": msg["user_id"], "nome": msg["nome"], "telefone_e164": msg["telefone_e164"], "mensagens": []}
        )
        grupo["mensagens"].append(msg)

    grupos = list(por_usuario.values())
    for grupo in grupos:
        corpo_combinado = "\n\n".join(m["corpo_renderizado"] for m in grupo["mensagens"])
        grupo["link_whatsapp_grupo"] = montar_link_whatsapp(grupo["telefone_e164"], corpo_combinado)
        grupo["excede_limite_grupo"] = excede_limite_caracteres(corpo_combinado)
    return grupos


@router.get("/envio")
def ver_envio(
    request: Request,
    cur: psycopg.Cursor = Depends(get_cursor),
    estado: EstadoRun = Depends(estado_run_hoje),
):
    from app.console.main import templates  # import tardio - ver nota em main.py

    agora = datetime.now(timezone.utc)
    expirar_mensagens_vencidas(cur, agora)

    slate_atual = buscar_slate_atual(cur, data_operacional())
    slate_status = slate_atual[1] if slate_atual else None
    acesso = avaliar_acesso_envio(estado, slate_status)
    if not acesso.liberado:
        return templates.TemplateResponse(request, "envio_bloqueado.html", {"acesso": acesso})

    fila = fila_envio(cur)
    mensagens = [_mensagem_para_exibicao(m) for m in fila]
    contexto = {
        "acesso": acesso,
        "grupos": _agrupar_por_assinante(mensagens),
        "contadores": contadores_do_dia(cur, agora),
    }
    return templates.TemplateResponse(request, "envio.html", contexto)


def _bloqueado_por_pausa(cur: psycopg.Cursor, modo: str) -> None:
    # D14: pausa e funcional, mas ESTREITA - so bloqueia o caminho
    # modo=sessao. O modo manual (/envio) nunca e afetado por uma sessao
    # pausada, mesmo que ela exista - os dois modos operam sobre a mesma
    # fila mas com gates independentes.
    if modo != "sessao":
        return
    sessao = buscar_sessao_aberta(cur, data_operacional())
    if sessao is not None and sessao.status == "pausada":
        raise HTTPException(status_code=409, detail="sessao de envio esta pausada")


@router.post("/envio/{message_id}/enviada", dependencies=[Depends(checar_origin)])
def post_marcar_enviada(
    message_id: str,
    modo: str = Form(default="manual"),
    conn: psycopg.Connection = Depends(get_conexao),
) -> RedirectResponse:
    with conn.cursor() as cur:
        _bloqueado_por_pausa(cur, modo)
        marcar_enviada(cur, message_id)
    conn.commit()
    # Mapeamento por literal, nunca redirect pra URL vinda do form - nao
    # abre superficie de open redirect.
    destino = "/envio/sessao" if modo == "sessao" else "/envio"
    return RedirectResponse(url=destino, status_code=303)


@router.post("/envio/{message_id}/pular", dependencies=[Depends(checar_origin)])
def post_pular(
    message_id: str,
    motivo: str = Form(...),
    modo: str = Form(default="manual"),
    conn: psycopg.Connection = Depends(get_conexao),
) -> RedirectResponse:
    if not motivo.strip():
        raise HTTPException(status_code=400, detail="motivo nao pode ser vazio")
    with conn.cursor() as cur:
        _bloqueado_por_pausa(cur, modo)
        pular(cur, message_id, motivo)
    conn.commit()
    destino = "/envio/sessao" if modo == "sessao" else "/envio"
    return RedirectResponse(url=destino, status_code=303)


def _parada_para_exibicao(parada) -> dict:
    return {
        "user_id": parada.user_id, "nome": parada.nome, "telefone_e164": parada.telefone_e164,
        "posicao": parada.posicao, "mensagens": [_mensagem_para_exibicao(m) for m in parada.mensagens],
    }


@router.get("/envio/sessao")
def ver_envio_sessao(
    request: Request,
    cur: psycopg.Cursor = Depends(get_cursor),
    estado: EstadoRun = Depends(estado_run_hoje),
):
    from app.console.main import templates  # import tardio - ver nota em main.py

    settings = get_settings()
    agora = datetime.now(timezone.utc)
    expirar_mensagens_vencidas(cur, agora)

    hoje = data_operacional()
    slate_atual = buscar_slate_atual(cur, hoje)
    slate_status = slate_atual[1] if slate_atual else None
    acesso_envio = avaliar_acesso_envio(estado, slate_status)
    if not acesso_envio.liberado:
        return templates.TemplateResponse(request, "envio_bloqueado.html", {"acesso": acesso_envio})

    sessao = buscar_sessao_aberta(cur, hoje)

    # D16: slate corrigido no meio de uma sessao em andamento - aviso na
    # tela, sessao continua (nao encerra automaticamente). Calculado
    # antes do auto-encerramento de D13 abaixo, que so se aplica quando
    # a fila zera.
    aviso_slate_mudou = sessao is not None and slate_atual is not None and sessao.slate_id != slate_atual[0]

    universo = universo_da_sessao(cur, hoje)
    fila = fila_envio(cur)
    paradas = montar_paradas(universo, fila, hoje)
    prog = progresso(paradas, universo, settings.intervalo_envio_segundos)

    resumo = None
    if sessao is not None and not paradas:
        # D13: sessao nunca expira por relogio (sem timeout de
        # inatividade), mas se a fila do dia zerou - todo mundo do
        # universo foi enviado/pulado/expirado - encerrar sozinha e um
        # encerramento honesto, nao um "abandono". Convergente so a
        # partir do estado real de messages, sem dado da requisicao -
        # seguro rodar num GET, mesmo precedente de
        # expirar_mensagens_vencidas (ver docstring dela).
        encerrar_sessao(cur, sessao.id, "sistema", "fila_vazia")
        enviadas, expiradas, prontas_restantes, puladas = resumo_do_dia(cur, hoje)
        resumo = montar_resumo(enviadas, expiradas, prontas_restantes, puladas)
        sessao = None

    acesso_sessao = avaliar_acesso_sessao(acesso_envio, sessao, paradas)
    parada = parada_atual(paradas)

    contexto = {
        "sessao": sessao,
        "acesso_sessao": acesso_sessao,
        "aviso_slate_mudou": aviso_slate_mudou,
        "progresso": prog,
        "parada": _parada_para_exibicao(parada) if parada is not None else None,
        "resumo": resumo,
        "intervalo_segundos": settings.intervalo_envio_segundos,
    }
    return templates.TemplateResponse(request, "envio_sessao.html", contexto)


@router.post("/envio/sessao/iniciar", dependencies=[Depends(checar_origin)])
def post_iniciar_sessao(
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    settings = get_settings()
    hoje = data_operacional()
    with conn.cursor() as cur:
        slate_atual = buscar_slate_atual(cur, hoje)
        slate_status = slate_atual[1] if slate_atual else None
        acesso_envio = avaliar_acesso_envio(estado, slate_status)
        if not acesso_envio.liberado:
            raise HTTPException(status_code=409, detail=acesso_envio.motivo_bloqueio)
        # acesso_envio.liberado garante slate_status == "aprovado" (ver
        # avaliar_acesso_envio), o que por sua vez garante slate_atual
        # nao-None - checar de novo aqui seria codigo morto.
        slate_id = slate_atual[0]

        universo = universo_da_sessao(cur, hoje)
        fila = fila_envio(cur)
        paradas = montar_paradas(universo, fila, hoje)
        sessao_existente = buscar_sessao_aberta(cur, hoje)
        acesso_sessao = avaliar_acesso_sessao(acesso_envio, sessao_existente, paradas)
        if not acesso_sessao.pode_iniciar:
            raise HTTPException(status_code=409, detail=acesso_sessao.motivo)

        if iniciar_sessao(cur, hoje, slate_id, settings.operador_nome) is None:
            raise HTTPException(status_code=409, detail="ja existe uma sessao de envio aberta hoje")
    conn.commit()
    return RedirectResponse(url="/envio/sessao", status_code=303)


def _exigir_sessao_aberta_de_hoje(cur: psycopg.Cursor, sessao_id: str) -> SessaoEnvio:
    # Espelha _exigir_pode_escrever (rotas_curadoria.py, Fase 5c): so
    # existir uma linha com esse id nao basta - envio_sessoes permite
    # mais de uma linha por dia (encerrada + nova), entao um sessao_id de
    # ontem ou ja encerrado nao pode mutar nada.
    sessao = buscar_sessao_aberta(cur, data_operacional())
    if sessao is None or sessao.id != sessao_id:
        raise HTTPException(status_code=409, detail="sessao nao e a sessao de envio aberta de hoje")
    return sessao


@router.post("/envio/sessao/{sessao_id}/pausar", dependencies=[Depends(checar_origin)])
def post_pausar_sessao(sessao_id: str, conn: psycopg.Connection = Depends(get_conexao)) -> RedirectResponse:
    with conn.cursor() as cur:
        _exigir_sessao_aberta_de_hoje(cur, sessao_id)
        if not pausar_sessao(cur, sessao_id):
            raise HTTPException(status_code=409, detail="sessao nao esta ativa")
    conn.commit()
    return RedirectResponse(url="/envio/sessao", status_code=303)


@router.post("/envio/sessao/{sessao_id}/retomar", dependencies=[Depends(checar_origin)])
def post_retomar_sessao(sessao_id: str, conn: psycopg.Connection = Depends(get_conexao)) -> RedirectResponse:
    with conn.cursor() as cur:
        _exigir_sessao_aberta_de_hoje(cur, sessao_id)
        if not retomar_sessao(cur, sessao_id):
            raise HTTPException(status_code=409, detail="sessao nao esta pausada")
    conn.commit()
    return RedirectResponse(url="/envio/sessao", status_code=303)


@router.post("/envio/sessao/{sessao_id}/encerrar", dependencies=[Depends(checar_origin)])
def post_encerrar_sessao(sessao_id: str, conn: psycopg.Connection = Depends(get_conexao)) -> RedirectResponse:
    settings = get_settings()
    with conn.cursor() as cur:
        _exigir_sessao_aberta_de_hoje(cur, sessao_id)
        encerrar_sessao(cur, sessao_id, settings.operador_nome, "manual")
    conn.commit()
    return RedirectResponse(url="/envio/sessao", status_code=303)
