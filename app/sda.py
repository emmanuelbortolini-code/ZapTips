"""Fetch e parsing da listagem do SDA (Sites de Apostas), Fase 2 Fonte 2.

REST do WordPress bloqueada (403, testado nesta sessao) - cai para HTML
com bs4, exatamente como o documento original previu.

Estrutura real confirmada nesta sessao: a listagem tem DOIS containers
`.tip-preview` na mesma pagina, cada um agrupando varios `article.
tip-preview-item` (os cards). Um container so tem cards com rotulo
"Começa em" (aba ativos), o outro so "Terminado" (aba encerrados) -
confirmado inspecionando 20 cards reais, 10 de cada. As duas abas tem
paginacao independente (elemento .pagination, um por aba, com totais bem
diferentes - 2 paginas vs milhares) mas usam o MESMO padrao de URL
/page/N. Por isso o status de cada card e decidido pelo rotulo dentro do
proprio card, nunca pela posicao no documento nem pela paginacao.

Principio da Fase 2: nao extrai mercado/selecao/odd/casa como campos
estruturados - isso e trabalho da Fase 3. `montar_texto_bruto` so
concatena o que ja esta claramente identificado (titulo, tipster, a
string de mercado inteira, casa citada), sem tentar separar mercado de
selecao de linha.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.sites-de-apostas.net"
LISTAGEM_URL = f"{BASE_URL}/prognosticos-noticias/category/prognosticos-de-apostas"
BRT = timezone(timedelta(hours=-3))

RATE_LIMIT_RECORRENTE_SEGUNDOS = 1.0
RATE_LIMIT_BACKFILL_SEGUNDOS = 3.0


@dataclass(frozen=True)
class SdaCard:
    url: str
    status: str  # "ativo" | "encerrado"
    titulo: str
    tipster: str | None
    tipster_url: str | None
    data: str | None  # DD.MM.YYYY cru
    hora: str | None  # HH:MM cru, BRT
    oneliner: str | None
    casa: str | None
    publicado_em: datetime | None


def limpar_url(url: str) -> str:
    partes = urlsplit(url)
    return urlunsplit((partes.scheme, partes.netloc, partes.path, "", ""))


def normalizar_repeticoes_adjacentes(texto: str) -> str:
    """Colapsa repeticao literal: "1.57 1.57" -> "1.57" (tokens
    separados por espaco), "SuperbetSuperbet" -> "Superbet"
    (concatenado sem separador). Blindagem para o achado do documento
    original sobre duplicacao de odd/casa em alguns cards."""
    if not texto:
        return texto

    tamanho = len(texto)
    if tamanho % 2 == 0:
        metade = tamanho // 2
        if metade > 0 and texto[:metade] == texto[metade:]:
            texto = texto[:metade]

    tokens = texto.split()
    colapsados: list[str] = []
    for tok in tokens:
        if not colapsados or colapsados[-1] != tok:
            colapsados.append(tok)
    return " ".join(colapsados)


def parse_listing_page(html: str) -> list[SdaCard]:
    soup = BeautifulSoup(html, "html.parser")
    cards: list[SdaCard] = []
    for artigo in soup.select("article.tip-preview-item"):
        card = _parse_card(artigo)
        if card is not None:
            cards.append(card)
    return cards


def _parse_card(artigo) -> SdaCard | None:
    link_el = artigo.select_one(".tip-preview__link")
    if link_el is None or not link_el.get("href"):
        return None
    url = limpar_url(link_el["href"])
    titulo = link_el.get_text(strip=True)

    texto_completo = artigo.get_text(" ")
    if "Terminado" in texto_completo:
        status = "encerrado"
    elif "Começa em" in texto_completo:
        status = "ativo"
    else:
        return None

    tipster_link = artigo.select_one("a.tip-preview__author-url")
    tipster_el = tipster_link.select_one(".tipster-name") if tipster_link else None
    tipster = tipster_el.get_text(strip=True) if tipster_el else None
    tipster_url = tipster_link.get("href") if tipster_link else None

    data_el = artigo.select_one(".tip-preview__event-date")
    data_raw = data_el.get_text(strip=True) if data_el else None

    hora_el = artigo.select_one(".tip-preview-event-time-hour")
    hora_raw = hora_el.get_text(strip=True) if hora_el else None

    oneliner_el = artigo.select_one(".tip-preview__cta-oneliner")
    oneliner = normalizar_repeticoes_adjacentes(oneliner_el.get_text(strip=True)) if oneliner_el else None

    casa_img = artigo.select_one(".tip-preview__cta img[alt]")
    casa = casa_img.get("alt") if casa_img else None

    return SdaCard(
        url=url,
        status=status,
        titulo=titulo,
        tipster=tipster,
        tipster_url=tipster_url,
        data=data_raw,
        hora=hora_raw,
        oneliner=oneliner,
        casa=casa,
        publicado_em=_combinar_data_hora(data_raw, hora_raw),
    )


def _combinar_data_hora(data_raw: str | None, hora_raw: str | None) -> datetime | None:
    if not data_raw:
        return None
    try:
        dia, mes, ano = (int(p) for p in data_raw.split("."))
    except ValueError:
        return None

    hora, minuto = 0, 0
    if hora_raw:
        try:
            hora, minuto = (int(p) for p in hora_raw.split(":"))
        except ValueError:
            pass

    try:
        brt = datetime(ano, mes, dia, hora, minuto, tzinfo=BRT)
    except ValueError:
        return None
    return brt.astimezone(timezone.utc)


def montar_texto_bruto(card: SdaCard) -> str:
    partes = [card.titulo]
    if card.tipster:
        partes.append(f"Tipster: {card.tipster}")
    if card.oneliner:
        partes.append(card.oneliner)
    if card.casa:
        partes.append(f"Casa: {card.casa}")
    return "\n".join(partes)


def fetch_listing_page(client: httpx.Client, page: int) -> str:
    url = LISTAGEM_URL if page <= 1 else f"{LISTAGEM_URL}/page/{page}"
    resp = client.get(url, timeout=20)
    resp.raise_for_status()
    return resp.text
