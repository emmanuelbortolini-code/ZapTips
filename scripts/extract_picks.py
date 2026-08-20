"""Extracao estruturada de palpites via Claude API (Fase 3, ver app/extraction.py).

Busca raw_picks nunca processados (extraido_em is null), extrai em lotes,
grava o resultado em picks e marca os posts respondidos como processados.
confianca_extracao < CONFIANCA_MINIMA vai para revisao_manual em vez de
extraido. casa_apostas e casado contra casas.nome (+ aliases) por
normalizacao simples (case-insensitive, sem fuzzy matching) - sem match,
casa_id fica null (aliases de casas ainda nao foram populados: vazio para
as 6 casas seedadas na migration 0009, ver CLAUDE.md). tipster vem de
raw_picks.autor (ja coletado na Fase 2, nao e campo extraido pelo modelo).

`raw_pick_id` e normalizado para `str` logo na leitura do banco
(psycopg devolve `uuid.UUID` por padrao para colunas uuid) - sem isso,
a comparacao de conjuntos contra os post_id (sempre `str`, vem do JSON
da resposta do modelo) nunca bate, e `posts_ausentes_na_resposta` dispara
sempre, mesmo quando o modelo respondeu certinho.

Duas fases de banco separadas (leitura curta, depois escrita), igual aos
coletores da Fase 2 - a chamada a API fica entre as duas, sem transacao
aberta durante o tempo de rede.

Uso:
    uv run python -m scripts.extract_picks
"""

import json
import sys

import anthropic
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.extraction import (
    CONFIANCA_MINIMA,
    ExtractedPalpite,
    RawPickInput,
    extrair_lote,
    montar_lotes,
)
from app.pipeline import ResultadoEtapa

log = structlog.get_logger()

MAX_POSTS_POR_LOTE = 20
# Preco por milhao de tokens do Haiku 4.5 (ver skill claude-api, tabela de
# modelos) - so para o relatorio de custo no console, nao afeta a chamada.
PRECO_INPUT_POR_MTOK = 1.00
PRECO_OUTPUT_POR_MTOK = 5.00


def buscar_raw_picks_pendentes(cur: psycopg.Cursor) -> list[RawPickInput]:
    cur.execute("select id, texto_bruto, autor from raw_picks where extraido_em is null order by coletado_em")
    return [RawPickInput(raw_pick_id=str(row[0]), texto_bruto=row[1], autor=row[2]) for row in cur.fetchall()]


def carregar_casas(cur: psycopg.Cursor) -> dict[str, str]:
    cur.execute("select id, nome, aliases from casas")
    casas: dict[str, str] = {}
    for casa_id, nome, aliases in cur.fetchall():
        casas[nome.strip().lower()] = casa_id
        for alias in aliases or []:
            casas[alias.strip().lower()] = casa_id
    return casas


def processar_lotes(
    client: anthropic.Anthropic, lotes: list[list[RawPickInput]]
) -> tuple[list[ExtractedPalpite], set[str], int, int]:
    todos_palpites: list[ExtractedPalpite] = []
    processados_ids: set[str] = set()
    total_input_tokens = 0
    total_output_tokens = 0

    for i, lote in enumerate(lotes, start=1):
        try:
            palpites, post_ids_respondidos, usage = extrair_lote(client, lote)
        except (anthropic.APIError, StopIteration, json.JSONDecodeError) as exc:
            # StopIteration: resposta sem bloco de texto (ex.: refusal).
            # JSONDecodeError: JSON truncado (ex.: stop_reason=max_tokens
            # no meio de um lote grande). Nenhum dos dois pode derrubar
            # lotes ja processados com sucesso antes dele - mesma licao
            # ja aplicada nos coletores da Fase 1/2 pra falha de rede.
            log.warning("falha_ao_extrair_lote", lote=i, erro=type(exc).__name__)
            continue

        ids_do_lote = {p.raw_pick_id for p in lote}
        faltantes = ids_do_lote - post_ids_respondidos
        if faltantes:
            log.warning("posts_ausentes_na_resposta", lote=i, quantidade=len(faltantes))

        todos_palpites.extend(palpites)
        processados_ids.update(post_ids_respondidos)
        total_input_tokens += usage.input_tokens
        total_output_tokens += usage.output_tokens

    return todos_palpites, processados_ids, total_input_tokens, total_output_tokens


def upsert_pick(cur: psycopg.Cursor, palpite: ExtractedPalpite, casa_id: str | None, tipster: str | None) -> None:
    status = "revisao_manual" if palpite.confianca_extracao < CONFIANCA_MINIMA else "extraido"
    cur.execute(
        """
        insert into picks (
            raw_pick_id, mercado, selecao, odd_citada, casa_id, confianca_tipster, status,
            time_casa, time_fora, competicao, data_referencia, unidades, tipster
        )
        values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """,
        (
            palpite.raw_pick_id, palpite.mercado, palpite.selecao, palpite.odd, casa_id,
            palpite.confianca_extracao, status,
            palpite.time_casa, palpite.time_fora, palpite.competicao, palpite.data_referencia,
            palpite.unidades, tipster,
        ),
    )


def marcar_extraidos(cur: psycopg.Cursor, raw_pick_ids: list[str]) -> None:
    if not raw_pick_ids:
        return
    cur.execute("update raw_picks set extraido_em = now() where id = any(%s::uuid[])", (raw_pick_ids,))


def executar() -> ResultadoEtapa:
    settings = get_settings()

    with get_connection() as conn:
        with conn.cursor() as cur:
            pendentes = buscar_raw_picks_pendentes(cur)
            casas = carregar_casas(cur)

    if not pendentes:
        return ResultadoEtapa(status="ok", itens_ok=0, itens_erro=0, detalhe={"pendentes": 0})

    if not settings.anthropic_api_key:
        # D3 (CLAUDE.md, Fase 5a): sem credito de API a etapa degrada, nao
        # falha - o resto do pipeline (matching, odds, slate) continua
        # rodando sobre o que ja foi extraido antes.
        return ResultadoEtapa(
            status="degradado",
            itens_ok=0,
            itens_erro=len(pendentes),
            detalhe={"motivo": "anthropic_api_key_ausente", "pendentes": len(pendentes)},
        )

    autor_por_raw_pick_id = {p.raw_pick_id: p.autor for p in pendentes}

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    lotes = montar_lotes(pendentes, MAX_POSTS_POR_LOTE)

    palpites, processados_ids, total_input_tokens, total_output_tokens = processar_lotes(client, lotes)

    custo = (
        total_input_tokens / 1_000_000 * PRECO_INPUT_POR_MTOK
        + total_output_tokens / 1_000_000 * PRECO_OUTPUT_POR_MTOK
    )

    with get_connection() as conn:
        with conn.cursor() as cur:
            for palpite in palpites:
                casa_id = casas.get((palpite.casa_apostas or "").strip().lower())
                tipster = autor_por_raw_pick_id.get(palpite.raw_pick_id)
                upsert_pick(cur, palpite, casa_id, tipster)
            marcar_extraidos(cur, list(processados_ids))
        conn.commit()

    faltantes = len(pendentes) - len(processados_ids)
    detalhe = {
        "pendentes": len(pendentes),
        "processados": len(processados_ids),
        "palpites": len(palpites),
        "tokens_entrada": total_input_tokens,
        "tokens_saida": total_output_tokens,
        "custo_estimado_usd": round(custo, 4),
    }
    return ResultadoEtapa(
        status="ok" if faltantes == 0 else "degradado", itens_ok=len(processados_ids), itens_erro=faltantes, detalhe=detalhe
    )


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    resultado = executar()
    print(f"{resultado.detalhe['pendentes']} raw_pick(s) pendente(s) de extracao.")

    if resultado.detalhe["pendentes"] == 0:
        return 0

    if resultado.detalhe.get("motivo") == "anthropic_api_key_ausente":
        print("ANTHROPIC_API_KEY vazia, abortando.")
        return 1

    print(
        f"{resultado.detalhe['palpites']} palpite(s) extraido(s) de {resultado.detalhe['processados']} post(s) "
        f"processado(s) (de {resultado.detalhe['pendentes']} pendentes)."
    )
    print(
        f"Tokens: {resultado.detalhe['tokens_entrada']} entrada / {resultado.detalhe['tokens_saida']} saida "
        f"| custo estimado: ${resultado.detalhe['custo_estimado_usd']:.4f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
