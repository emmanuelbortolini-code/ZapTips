"""Coletor de palpites do SDA / Sites de Apostas (Fase 2, Fonte 2).

REST do WordPress bloqueada (403, testado nesta sessao); HTML com bs4
(ver app/sda.py). Captura o card inteiro em texto sem separar mercado/
selecao/odd - isso e trabalho da Fase 3. Essa fonte ja cita casa
licenciada no Brasil junto do palpite (migrations 0008/0009), o que a
torna origem preferencial de odd_referencia (nivel 1 da hierarquia)
quando a Fase 3/4 existir.

Dois modos, replicando a distincao do documento original:

- Recorrente (padrao): so cards com rotulo "Começa em", paginando ate uma
  pagina inteira nao trazer card novo (nunca visto antes por URL).
- Backfill (`--backfill`): so cards com rotulo "Terminado", paginando ate
  90 dias atras. Roda uma vez so, na largada - repetir so desperdica
  requisicoes, ja que a deduplicacao por hash_conteudo barra tudo.

Achado real desta sessao: a listagem tem duas paginacoes independentes
(elemento .pagination, uma por aba) mas ambas usam o MESMO padrao de URL
/page/N - por isso o filtro por status de cada card (nunca por posicao ou
pela paginacao) e essencial nos dois modos.

Fonte nasce em quarentena por padrao (sources.quarentena = true).

Uso:
    uv run python -m scripts.collect_sda              # recorrente
    uv run python -m scripts.collect_sda --backfill    # backfill de 90 dias
"""

import hashlib
import sys
import time
from datetime import datetime, timedelta, timezone

import httpx
import psycopg
import structlog

from app.config import get_settings
from app.db import get_connection
from app.sda import (
    LISTAGEM_URL,
    RATE_LIMIT_BACKFILL_SEGUNDOS,
    RATE_LIMIT_RECORRENTE_SEGUNDOS,
    SdaCard,
    fetch_listing_page,
    montar_texto_bruto,
    parse_listing_page,
)
from app.pipeline import ResultadoEtapa
from app.sources import upsert_source

log = structlog.get_logger()

NOME_FONTE = "Sites de Apostas"
BACKFILL_DIAS = 90
PAGINAS_MAXIMAS_RECORRENTE = 20
PAGINAS_MAXIMAS_BACKFILL = 100


def calcular_hash_conteudo(card: SdaCard, texto_bruto: str) -> str:
    base = f"{card.url}:{texto_bruto}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def upsert_raw_pick(
    cur: psycopg.Cursor, source_id: str, card: SdaCard, texto_bruto: str, hash_conteudo: str
) -> tuple[str, bool]:
    cur.execute(
        """
        insert into raw_picks (source_id, texto_bruto, url_origem, autor, publicado_em, hash_conteudo)
        values (%s, %s, %s, %s, %s, %s)
        on conflict (hash_conteudo) do nothing
        returning id
        """,
        (source_id, texto_bruto, card.url, card.tipster, card.publicado_em, hash_conteudo),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0], True

    cur.execute("select id from raw_picks where hash_conteudo = %s", (hash_conteudo,))
    return cur.fetchone()[0], False


def buscar_urls_ja_coletadas(cur: psycopg.Cursor, source_id: str) -> set[str]:
    cur.execute("select url_origem from raw_picks where source_id = %s", (source_id,))
    return {row[0] for row in cur.fetchall() if row[0]}


def buscar_cards_recorrente(client: httpx.Client, urls_conhecidas: set[str]) -> list[SdaCard]:
    coletados: list[SdaCard] = []
    urls_conhecidas = set(urls_conhecidas)

    for pagina in range(1, PAGINAS_MAXIMAS_RECORRENTE + 1):
        try:
            html = fetch_listing_page(client, pagina)
        except httpx.HTTPError as exc:
            log.warning("falha_ao_buscar_pagina", pagina=pagina, erro=type(exc).__name__)
            break

        ativos = [c for c in parse_listing_page(html) if c.status == "ativo"]
        novos = [c for c in ativos if c.url not in urls_conhecidas]
        if not novos:
            break

        coletados.extend(novos)
        urls_conhecidas.update(c.url for c in novos)
        time.sleep(RATE_LIMIT_RECORRENTE_SEGUNDOS)

    return coletados


def buscar_cards_backfill(client: httpx.Client) -> list[SdaCard]:
    corte = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DIAS)
    coletados: list[SdaCard] = []

    for pagina in range(1, PAGINAS_MAXIMAS_BACKFILL + 1):
        try:
            html = fetch_listing_page(client, pagina)
        except httpx.HTTPError as exc:
            log.warning("falha_ao_buscar_pagina", pagina=pagina, erro=type(exc).__name__)
            break

        encerrados = [c for c in parse_listing_page(html) if c.status == "encerrado"]
        if not encerrados:
            break

        coletados.extend(encerrados)

        com_data = [c.publicado_em for c in encerrados if c.publicado_em is not None]
        if com_data and min(com_data) < corte:
            break

        time.sleep(RATE_LIMIT_BACKFILL_SEGUNDOS)

    return coletados


def executar() -> ResultadoEtapa:
    # So o modo recorrente entra no pipeline diario (Fase 5a) - backfill
    # roda uma vez so, manual, na largada (ver docstring do modulo).
    with get_connection() as conn:
        with conn.cursor() as cur:
            source_id = upsert_source(cur, NOME_FONTE, "site", LISTAGEM_URL)
            urls_conhecidas = buscar_urls_ja_coletadas(cur, source_id)
        conn.commit()

    with httpx.Client() as client:
        cards = buscar_cards_recorrente(client, urls_conhecidas)

    novos = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for card in cards:
                texto_bruto = montar_texto_bruto(card)
                hash_conteudo = calcular_hash_conteudo(card, texto_bruto)
                _, novo = upsert_raw_pick(cur, source_id, card, texto_bruto, hash_conteudo)
                novos += int(novo)
        conn.commit()

    detalhe = {"modo": "recorrente", "cards_coletados": len(cards), "ja_existentes": len(cards) - novos}
    return ResultadoEtapa(status="ok", itens_ok=novos, itens_erro=0, detalhe=detalhe)


def _executar_backfill() -> ResultadoEtapa:
    with get_connection() as conn:
        with conn.cursor() as cur:
            source_id = upsert_source(cur, NOME_FONTE, "site", LISTAGEM_URL)
        conn.commit()

    with httpx.Client() as client:
        cards = buscar_cards_backfill(client)

    novos = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for card in cards:
                texto_bruto = montar_texto_bruto(card)
                hash_conteudo = calcular_hash_conteudo(card, texto_bruto)
                _, novo = upsert_raw_pick(cur, source_id, card, texto_bruto, hash_conteudo)
                novos += int(novo)
        conn.commit()

    detalhe = {"modo": "backfill", "cards_coletados": len(cards), "ja_existentes": len(cards) - novos}
    return ResultadoEtapa(status="ok", itens_ok=novos, itens_erro=0, detalhe=detalhe)


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    if "--backfill" in sys.argv:
        print(f"Modo backfill: ate {BACKFILL_DIAS} dias atras.")
        resultado = _executar_backfill()
    else:
        print("Modo recorrente.")
        resultado = executar()

    print(f"{resultado.detalhe['cards_coletados']} card(s) coletado(s).")
    print(f"raw_picks novos: {resultado.itens_ok} | ja existentes: {resultado.detalhe['ja_existentes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
