"""Fetch e parsing do canal publico do Telegram do Eagle Predict (Fase 2,
Fonte 1).

Estrategia: HTML, sem Telethon. O canal e publico e o Telegram serve uma
versao renderizada no servidor em `t.me/s/{canal}` - UA default do httpx
funciona sem 403 (diferente da ESPN).

Principio da Fase 2: captura o texto do post inteiro, sem tentar extrair
mercado/selecao/odd/data de kickoff aqui. O layout do canal muda de
tempos em tempos; extracao estruturada e trabalho do modelo na Fase 3.

Achado real que nao estava no material original: uma mensagem que e
resposta (reply) a outra tem DOIS blocos com a classe base
"tgme_widget_message_text" no DOM - o da citacao truncada da mensagem
respondida (classe extra "js-message_reply_text") vem ANTES do texto real
da propria mensagem (classe extra "js-message_text"). Um seletor generico
so na classe base pega o bloco errado. Sempre usar o seletor composto
".js-message_text".

Marcador do documento original ("Football Betting Tip", ASCII liso) nao
existe nos posts reais - o canal usa fonte unicode estilizada que muda
("Football Tip 2" em mathematical sans-serif bold, por exemplo). "Odds @"
e o marcador estavel encontrado: texto plano, presente em todo post real
de tip e ausente de post promocional, validado contra 20 mensagens reais
do canal (9 tips, 11 promo/outros, zero falso positivo/negativo).
"""

from dataclasses import dataclass
from datetime import datetime

import httpx
from bs4 import BeautifulSoup

CANAL = "eaglepredict"
MARCADOR_TIP = "Odds @"
TAMANHO_PAGINA = 20

# Nao documentado como limite formal (diferente da ESPN/OddsPapi), mas
# mesmo espirito de nao abusar do host - ver CLAUDE.md, Fase 1a.
RATE_LIMIT_SECONDS = 1.0


@dataclass(frozen=True)
class TelegramPost:
    message_id: str
    url: str
    published_at: datetime
    texto: str


def parse_channel_page(html: str, canal: str) -> list[TelegramPost]:
    soup = BeautifulSoup(html, "html.parser")
    posts: list[TelegramPost] = []
    for bloco in soup.select("div.tgme_widget_message"):
        post = _parse_bloco(bloco, canal)
        if post is not None:
            posts.append(post)
    return posts


def _parse_bloco(bloco, canal: str) -> TelegramPost | None:
    data_post = bloco.get("data-post")
    if not data_post:
        return None

    texto_el = bloco.select_one(".tgme_widget_message_text.js-message_text")
    time_el = bloco.select_one("time.time")
    if texto_el is None or time_el is None:
        return None

    datetime_raw = time_el.get("datetime")
    if not datetime_raw:
        return None

    try:
        published_at = datetime.fromisoformat(datetime_raw)
    except ValueError:
        return None

    message_id = data_post.rsplit("/", 1)[-1]
    return TelegramPost(
        message_id=message_id,
        url=f"https://t.me/{canal}/{message_id}",
        published_at=published_at,
        texto=texto_el.get_text("\n").strip(),
    )


def is_betting_tip_post(texto: str) -> bool:
    return MARCADOR_TIP in texto


def fetch_channel_page(
    client: httpx.Client, canal: str, before: str | None = None, after: str | None = None
) -> str:
    params: dict[str, str] = {}
    if before:
        params["before"] = before
    if after:
        params["after"] = after
    resp = client.get(f"https://t.me/s/{canal}", params=params, timeout=20)
    resp.raise_for_status()
    return resp.text
