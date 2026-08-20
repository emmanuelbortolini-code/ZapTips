"""Rota da aba Curadoria (Fase 5c) - bloqueada enquanto a execucao nao
chegar na etapa `slate` (app.console.rules.avaliar_acesso_curadoria).
So leitura nesta rota; acoes (remover/editar/aprovar) entram na Fase D/E
deste mesmo pacote."""

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation

import psycopg
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from app.config import get_settings
from app.messages_generator import gerar_mensagens
from app.console.acoes import (
    FixturaInvalida,
    MercadoInvalido,
    PisoAbaixoDoAbsoluto,
    aprovar_slate,
    criar_palpite_manual,
    editar_odd_referencia,
    editar_piso,
    gerar_correcao,
    remover_item,
    reordenar_item,
    resolver_conflito_descartar_todas,
    resolver_conflito_usar_selecao,
)
from app.console.deps import checar_origin, estado_run_hoje, get_conexao, get_cursor
from app.console.queries import (
    EstadoRun,
    ItemSlate,
    buscar_slate_atual,
    buscar_status_slate,
    carregar_itens_slate,
    conflitos_por_fixture,
    excluidos_do_dia,
    existe_pick_quarentena_no_slate,
    fixturas_elegiveis_do_dia,
    picks_do_dia,
)
from app.console.rules import Bloqueio, avaliar_acesso_curadoria, bloqueios_de_aprovacao, tem_alerta_divergencia
from app.pipeline import FUSO_OPERACIONAL, data_operacional

router = APIRouter()


def _exigir_pode_escrever(cur: psycopg.Cursor, estado: EstadoRun, slate_id: str) -> None:
    # Checado de novo em toda escrita, nunca so uma vez no GET - o
    # operador pode ter a pagina aberta ha minutos enquanto o estado do
    # pipeline/slate muda por baixo.
    acesso = avaliar_acesso_curadoria(estado)
    if not acesso.liberado:
        raise HTTPException(status_code=409, detail=acesso.motivo_bloqueio)

    # Confirma que slate_id e de fato o rascunho ATUAL de hoje, nao so
    # "alguma linha de daily_slates com esse id e status='rascunho'"
    # (achado HIGH do security-reviewer, Fase 5c): daily_slates permite
    # mais de uma linha por data desde a migration 0014 (cadeia de
    # correcao), entao um slate_id de rascunho antigo/abandonado
    # passaria pela checagem anterior sem ser o que a pagina de hoje
    # mostra.
    atual = buscar_slate_atual(cur, data_operacional())
    if atual is None or atual[0] != slate_id or atual[1] != "rascunho":
        raise HTTPException(status_code=409, detail="slate nao e o rascunho atual de hoje")


def _item_para_exibicao(item: ItemSlate, limite_divergencia_pct: float) -> dict:
    return {
        **item.__dict__,
        "kickoff_local": item.kickoff_utc.astimezone(FUSO_OPERACIONAL),
        "divergencia": tem_alerta_divergencia(item, limite_divergencia_pct),
    }


def _pick_do_dia_para_exibicao(pick) -> dict:
    return {**pick.__dict__, "kickoff_local": pick.kickoff_utc.astimezone(FUSO_OPERACIONAL)}


@router.get("/curadoria")
def ver_curadoria(
    request: Request,
    cur: psycopg.Cursor = Depends(get_cursor),
    estado: EstadoRun = Depends(estado_run_hoje),
):
    from app.console.main import templates  # import tardio - ver nota em main.py

    acesso = avaliar_acesso_curadoria(estado)
    if not acesso.liberado:
        return templates.TemplateResponse(request, "curadoria_bloqueada.html", {"acesso": acesso})

    settings = get_settings()
    fixturas_elegiveis = fixturas_elegiveis_do_dia(cur)
    picks_dia = [_pick_do_dia_para_exibicao(pick) for pick in picks_do_dia(cur)]

    slate_row = buscar_slate_atual(cur, data_operacional())
    if slate_row is None:
        contexto = {
            "acesso": acesso, "itens": [], "conflitos": {}, "excluidos": [],
            "slate_id": None, "slate_status": None, "substitui_slate_id": None, "bloqueios": (),
            "fixturas_elegiveis": fixturas_elegiveis, "picks_dia": picks_dia,
        }
        return templates.TemplateResponse(request, "curadoria.html", contexto)

    slate_id, slate_status, substitui_slate_id = slate_row
    itens = carregar_itens_slate(cur, slate_id)
    fixture_ids = list({item.fixture_id for item in itens})
    conflitos = conflitos_por_fixture(cur, fixture_ids)

    contexto = {
        "acesso": acesso,
        "itens": [_item_para_exibicao(item, settings.divergencia_odd_alerta_pct) for item in itens],
        "conflitos": conflitos,
        "excluidos": excluidos_do_dia(cur, fixture_ids),
        "slate_id": slate_id,
        "slate_status": slate_status,
        "substitui_slate_id": substitui_slate_id,
        "bloqueios": bloqueios_de_aprovacao(itens, conflitos, settings.odd_minima_absoluta),
        "fixturas_elegiveis": fixturas_elegiveis,
        "picks_dia": picks_dia,
    }
    return templates.TemplateResponse(request, "curadoria.html", contexto)


@router.post("/curadoria/{slate_id}/remover/{slate_pick_id}", dependencies=[Depends(checar_origin)])
def post_remover_item(
    slate_id: str,
    slate_pick_id: str,
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        remover_item(cur, slate_id, slate_pick_id)
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/reordenar/{slate_pick_id}", dependencies=[Depends(checar_origin)])
def post_reordenar_item(
    slate_id: str,
    slate_pick_id: str,
    direcao: str = Form(...),
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    if direcao not in ("subir", "descer"):
        raise HTTPException(status_code=400, detail="direcao invalida - use 'subir' ou 'descer'")
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        reordenar_item(cur, slate_id, slate_pick_id, direcao)
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/piso/{slate_pick_id}", dependencies=[Depends(checar_origin)])
def post_editar_piso(
    slate_id: str,
    slate_pick_id: str,
    novo_piso: str = Form(...),
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    try:
        valor = Decimal(novo_piso)
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"piso invalido: {novo_piso!r}")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="piso precisa ser maior que zero")

    settings = get_settings()
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        try:
            editar_piso(cur, slate_id, slate_pick_id, valor, settings.odd_minima_absoluta)
        except PisoAbaixoDoAbsoluto as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/odd-referencia/{slate_pick_id}", dependencies=[Depends(checar_origin)])
def post_editar_odd_referencia(
    slate_id: str,
    slate_pick_id: str,
    nova_odd: str = Form(...),
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    try:
        valor = Decimal(nova_odd)
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"odd invalida: {nova_odd!r}")
    if valor <= 0:
        raise HTTPException(status_code=400, detail="odd precisa ser maior que zero")

    settings = get_settings()
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        editar_odd_referencia(cur, slate_id, slate_pick_id, valor, settings.margem_pct, settings.odd_minima_absoluta)
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


def _itens_e_conflitos(cur: psycopg.Cursor, slate_id: str) -> tuple[tuple[ItemSlate, ...], dict]:
    itens = carregar_itens_slate(cur, slate_id)
    fixture_ids = list({item.fixture_id for item in itens})
    return itens, conflitos_por_fixture(cur, fixture_ids)


@router.post("/curadoria/{slate_id}/aprovar", dependencies=[Depends(checar_origin)])
def post_aprovar_slate(
    slate_id: str,
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    settings = get_settings()
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)

        # Re-checa os bloqueios aqui, nao so confia no que a pagina
        # renderizou - o estado pode ter mudado entre o GET e este POST.
        itens, conflitos = _itens_e_conflitos(cur, slate_id)
        bloqueios = list(bloqueios_de_aprovacao(itens, conflitos, settings.odd_minima_absoluta))

        # Defesa em profundidade (achado CRITICAL do code-reviewer, Fase
        # 5c): confirma direto em slate_picks, independente de como um
        # item quarentenado teria chegado la (build_slate.py e
        # conflitos_por_fixture ja filtram na origem, mas aprovar_slate
        # nunca deveria confiar so nisso pra uma acao irreversivel).
        if existe_pick_quarentena_no_slate(cur, slate_id):
            bloqueios.append(Bloqueio("quarentena_no_slate", "Ha pick de fonte em quarentena neste slate."))

        if bloqueios:
            raise HTTPException(status_code=409, detail="; ".join(b.mensagem for b in bloqueios))

        if not aprovar_slate(cur, slate_id, curado_por=settings.operador_nome):
            raise HTTPException(status_code=409, detail="slate nao esta em rascunho - nao ha o que aprovar")

        # D1 (Fase 5d): geracao de mensagem acontece na mesma transacao
        # da aprovacao - se a geracao falhar, a aprovacao tambem nao
        # acontece (rollback), em vez de deixar um "aprovado sem
        # mensagem" que ninguem percebe. QUEUE_ENABLED e checado dentro
        # de gerar_mensagens, unico choke point.
        gerar_mensagens(cur, data_operacional(), datetime.now(timezone.utc), settings)
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/gerar-correcao", dependencies=[Depends(checar_origin)])
def post_gerar_correcao(
    slate_id: str,
    conn: psycopg.Connection = Depends(get_conexao),
) -> RedirectResponse:
    # Gerar correcao so se aplica a um slate JA aprovado - _exigir_pode_escrever
    # (que recusa quando status != 'rascunho') nao serve aqui de proposito.
    with conn.cursor() as cur:
        status = buscar_status_slate(cur, slate_id)
        if status != "aprovado":
            raise HTTPException(status_code=409, detail="so e possivel gerar correcao de um slate aprovado")
        gerar_correcao(cur, slate_id)
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/conflito/usar/{pick_id}", dependencies=[Depends(checar_origin)])
def post_resolver_conflito_usar_selecao(
    slate_id: str,
    pick_id: str,
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        itens, _ = _itens_e_conflitos(cur, slate_id)
        fixture_ids = list({item.fixture_id for item in itens})
        if not resolver_conflito_usar_selecao(cur, slate_id, pick_id, fixture_ids):
            raise HTTPException(status_code=409, detail="pick nao esta em conflito nas fixtures deste slate")
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/conflito/descartar", dependencies=[Depends(checar_origin)])
def post_resolver_conflito_descartar_todas(
    slate_id: str,
    pick_ids: str = Form(...),  # csv de uuids, vem de um campo hidden no form
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        itens, _ = _itens_e_conflitos(cur, slate_id)
        fixture_ids = list({item.fixture_id for item in itens})
        resolver_conflito_descartar_todas(
            cur, slate_id, [p.strip() for p in pick_ids.split(",") if p.strip()], fixture_ids,
            motivo="conflito de selecoes sem consenso - descartado manualmente na curadoria",
        )
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)


@router.post("/curadoria/{slate_id}/palpite-manual", dependencies=[Depends(checar_origin)])
def post_criar_palpite_manual(
    slate_id: str,
    fixture_id: str = Form(...),
    mercado: str = Form(...),
    selecao: str = Form(...),
    odd_referencia: str = Form(...),
    conn: psycopg.Connection = Depends(get_conexao),
    estado: EstadoRun = Depends(estado_run_hoje),
) -> RedirectResponse:
    try:
        valor_odd = Decimal(odd_referencia)
    except InvalidOperation:
        raise HTTPException(status_code=400, detail=f"odd invalida: {odd_referencia!r}")
    if valor_odd <= 0:
        raise HTTPException(status_code=400, detail="odd precisa ser maior que zero")
    if not selecao.strip():
        raise HTTPException(status_code=400, detail="selecao nao pode ser vazia")

    settings = get_settings()
    with conn.cursor() as cur:
        _exigir_pode_escrever(cur, estado, slate_id)
        try:
            criar_palpite_manual(
                cur, slate_id=slate_id, fixture_id=fixture_id, mercado=mercado, selecao=selecao.strip(),
                odd_referencia=valor_odd, operador_nome=settings.operador_nome,
                odd_minima_absoluta=settings.odd_minima_absoluta, margem_pct=settings.margem_pct,
            )
        except (MercadoInvalido, FixturaInvalida, PisoAbaixoDoAbsoluto) as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    conn.commit()
    return RedirectResponse(url="/curadoria", status_code=303)
