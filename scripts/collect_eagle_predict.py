"""Coletor de palpites do Eagle Predict (Fase 2, Fonte 1).

Canal publico do Telegram, sem Telethon (ver app/eagle_predict.py).
Captura o texto do post inteiro sem tentar extrair mercado/selecao/odd -
isso e trabalho da Fase 3. So filtra por "Odds @" para descartar post
promocional/bonus (ver achados reais no docstring de app/eagle_predict.py).

Primeira execucao faz backfill de ~90 dias, paginando pra tras com
`before=` a partir do post mais recente, parando quando a pagina mais
antiga passa do corte de data ou quando o canal acaba. Execucoes
seguintes usam `after=` a partir do ultimo id ja coletado (extraido de
`raw_picks.url_origem`), evitando reprocessar tudo.

Fonte nasce em quarentena por padrao (`sources.quarentena = true` ja e o
default da coluna) - sair e decisao do PM, nunca configuracao default
(ver documento original, "Regras de quarentena").

Idempotente: `raw_picks.hash_conteudo` e unico (migration 0001); o hash
combina id da mensagem + texto, entao uma mensagem editada gera um
hash novo (vira um raw_pick novo) em vez de silenciosamente sumir.

Uso:
    uv run python -m scripts.collect_eagle_predict
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
from app.eagle_predict import (
    CANAL,
    RATE_LIMIT_SECONDS,
    TAMANHO_PAGINA,
    TelegramPost,
    fetch_channel_page,
    is_betting_tip_post,
    parse_channel_page,
)
from app.pipeline import ResultadoEtapa
from app.sources import upsert_source

log = structlog.get_logger()

NOME_FONTE = "Eagle Predict"
BACKFILL_DIAS = 90
PAGINAS_MAXIMAS = 60  # trava de seguranca, nao deixa paginar pra sempre


def calcular_hash_conteudo(canal: str, post: TelegramPost) -> str:
    # message_id do Telegram e unico por canal, nao globalmente - inclui o
    # canal no hash para nao colidir quando uma segunda fonte de Telegram
    # entrar (hash_conteudo e unique em raw_picks inteiro, nao por fonte).
    base = f"{canal}:{post.message_id}:{post.texto}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def upsert_raw_pick(
    cur: psycopg.Cursor, source_id: str, post: TelegramPost, hash_conteudo: str
) -> tuple[str, bool]:
    cur.execute(
        """
        insert into raw_picks (source_id, texto_bruto, url_origem, publicado_em, hash_conteudo)
        values (%s, %s, %s, %s, %s)
        on conflict (hash_conteudo) do nothing
        returning id
        """,
        (source_id, post.texto, post.url, post.published_at, hash_conteudo),
    )
    row = cur.fetchone()
    if row is not None:
        return row[0], True

    cur.execute("select id from raw_picks where hash_conteudo = %s", (hash_conteudo,))
    return cur.fetchone()[0], False


def buscar_ultimo_id_coletado(cur: psycopg.Cursor, source_id: str) -> str | None:
    cur.execute(
        "select url_origem from raw_picks where source_id = %s order by publicado_em desc limit 1",
        (source_id,),
    )
    row = cur.fetchone()
    if row is None or not row[0]:
        return None
    return row[0].rstrip("/").rsplit("/", 1)[-1]


def buscar_posts(
    client: httpx.Client,
    canal: str,
    *,
    before: str | None = None,
    after: str | None = None,
    parar_antes_de: datetime | None = None,
) -> list[TelegramPost]:
    todos: list[TelegramPost] = []
    cursor_before = before
    cursor_after = after

    for _ in range(PAGINAS_MAXIMAS):
        try:
            html = fetch_channel_page(client, canal, before=cursor_before, after=cursor_after)
        except httpx.HTTPError as exc:
            # Mesmo padrao dos outros coletores: uma falha no meio da
            # paginacao nao pode jogar fora as paginas ja buscadas (podem
            # ser dezenas de requisicoes ja pagas em tempo de rate limit).
            log.warning("falha_ao_buscar_pagina", canal=canal, erro=type(exc).__name__)
            break

        posts = parse_channel_page(html, canal)
        if not posts:
            break
        todos.extend(posts)

        if cursor_after is not None:
            cursor_after = max(posts, key=lambda p: p.published_at).message_id
            if len(posts) < TAMANHO_PAGINA:
                break
        else:
            mais_antigo = min(posts, key=lambda p: p.published_at)
            if parar_antes_de and mais_antigo.published_at < parar_antes_de:
                break
            cursor_before = mais_antigo.message_id

        time.sleep(RATE_LIMIT_SECONDS)

    return todos


def executar() -> ResultadoEtapa:
    with get_connection() as conn:
        with conn.cursor() as cur:
            source_id = upsert_source(cur, NOME_FONTE, "telegram", f"https://t.me/s/{CANAL}")
            ultimo_id = buscar_ultimo_id_coletado(cur, source_id)
        conn.commit()

    with httpx.Client() as client:
        if ultimo_id is None:
            corte = datetime.now(timezone.utc) - timedelta(days=BACKFILL_DIAS)
            posts = buscar_posts(client, CANAL, parar_antes_de=corte)
            modo = "backfill"
        else:
            posts = buscar_posts(client, CANAL, after=ultimo_id)
            modo = "incremental"

    tips = [p for p in posts if is_betting_tip_post(p.texto)]

    novos = 0
    with get_connection() as conn:
        with conn.cursor() as cur:
            for post in tips:
                _, novo = upsert_raw_pick(cur, source_id, post, calcular_hash_conteudo(CANAL, post))
                novos += int(novo)
        conn.commit()

    detalhe = {
        "modo": modo,
        "ultimo_id_anterior": ultimo_id,
        "posts_verificados": len(posts),
        "tips_encontrados": len(tips),
        "ja_existentes": len(tips) - novos,
    }
    return ResultadoEtapa(status="ok", itens_ok=novos, itens_erro=0, detalhe=detalhe)


def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        print("DATABASE_URL vazia, abortando.")
        return 1

    resultado = executar()
    if resultado.detalhe["modo"] == "backfill":
        print(f"Primeira execucao: backfill de {BACKFILL_DIAS} dias.")
    else:
        print(f"Coleta incremental a partir de {resultado.detalhe['ultimo_id_anterior']}.")
    print(f"{resultado.detalhe['posts_verificados']} post(s) verificado(s), {resultado.detalhe['tips_encontrados']} com marcador de tip.")
    print(f"raw_picks novos: {resultado.itens_ok} | ja existentes: {resultado.detalhe['ja_existentes']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
