"""Fetch e parsing do APWin Decreasing Stats (documento original, "Fonte
4: APWin Decreasing Stats", QUARENTENA). Mercado vem da PAGINA (URL), nao
do texto - cada pagina e um mercado fixo, com selecao/linha tambem fixas
(confirmado contra o site real em 2026-08-25, ver `PAGINAS`). Isso e o
que permite essa fonte pular a extracao via Claude (app/extraction.py) e
ir direto de raw_pick pra pick estruturado - trabalho de
scripts/collect_apwin.py, nao deste modulo.

Escopo desta entrega: so as 4 paginas cujo mercado ja e' totalmente
suportado por app/settlement/engine.py (jogo inteiro, nao "por
time"/1o tempo). As paginas "team-over-*"/"team-scored-in-both-halves"/
"over-ht-goals" ficam de fora de proposito - ver CLAUDE.md pendencia 4
("cartoes, condicao por time") pro mesmo motivo de cautela.

So entradas 100% aparecem nas paginas por padrao (confirmado: 16/16 numa
amostra real de BTTS) - bate com o documento original ("filtro: apenas
100%"). Grupo de comparacao abaixo de 100% (pro relatorio de decisao da
quarentena) fica fora desta entrega - nao ha parametro de URL simples
pra pedir isso, so um dropdown que parece Livewire/AJAX.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

import httpx
from bs4 import BeautifulSoup

BASE_URL = "https://www.apwin.com/decreasing-stats"
BRT = timezone(timedelta(hours=-3))

RATE_LIMIT_SEGUNDOS = 1.0

Mercado = Literal["ambas_marcam", "over_under", "escanteios", "cartoes"]


@dataclass(frozen=True)
class PaginaMercado:
    slug: str  # "" para a pagina raiz (BTTS)
    mercado: Mercado
    selecao: str
    linha: float | None


# Linha/selecao confirmadas contra o site real em 2026-08-25 (titulo e
# rotulo de cada pagina, nao adivinhadas): "Matches with Both Teams to
# Score Today", "Matches with Over 2.5 Goals Today", "Matches with Over
# 9.5 Corners Today", "Matches with Over 4.5 Cards Today".
PAGINAS: tuple[PaginaMercado, ...] = (
    PaginaMercado(slug="", mercado="ambas_marcam", selecao="sim", linha=None),
    PaginaMercado(slug="over-goals", mercado="over_under", selecao="over", linha=2.5),
    PaginaMercado(slug="over-corners", mercado="escanteios", selecao="over", linha=9.5),
    PaginaMercado(slug="over-45-cards", mercado="cartoes", selecao="over", linha=4.5),
)


@dataclass(frozen=True)
class ApwinEntrada:
    match_id: str
    match_url: str
    kickoff_brt_texto: str  # "DD/MM/YYYY HH:MM" cru
    kickoff_utc: datetime | None
    liga_texto: str | None
    time_casa_texto: str
    time_fora_texto: str
    percentual: float


def url_pagina(pagina: PaginaMercado) -> str:
    if pagina.slug:
        return f"{BASE_URL}/{pagina.slug}/"
    return f"{BASE_URL}/"


def fetch_market_page(client: httpx.Client, pagina: PaginaMercado) -> str:
    resp = client.get(url_pagina(pagina), timeout=20)
    resp.raise_for_status()
    return resp.text


def _combinar_data_hora(texto: str) -> datetime | None:
    # "25/08/2026 20:45", sempre BRT (achado real: pagina serve o
    # horario local do time da casa? nao verificado - o documento
    # original nao especifica timezone; BRT e' a mesma suposicao ja
    # usada pro SDA, e o unico timezone que este projeto trata como
    # "hora local do palpite" em qualquer fonte).
    try:
        data_parte, hora_parte = texto.split(" ", 1)
        dia, mes, ano = (int(p) for p in data_parte.split("/"))
        hora, minuto = (int(p) for p in hora_parte.split(":"))
        return datetime(ano, mes, dia, hora, minuto, tzinfo=BRT).astimezone(timezone.utc)
    except (ValueError, AttributeError):
        return None


def parse_market_page(html: str) -> list[ApwinEntrada]:
    soup = BeautifulSoup(html, "html.parser")
    tabela = soup.select_one("#stats-table")
    if tabela is None:
        return []

    entradas: list[ApwinEntrada] = []
    for linha in tabela.select(".stats-item"):
        entrada = _parse_linha(linha)
        if entrada is not None:
            entradas.append(entrada)
    return entradas


def _parse_linha(linha) -> ApwinEntrada | None:
    # A primeira ".column.is-size-7" da linha e a de data/liga - a
    # ultima coluna (percentual/link) tem as MESMAS duas classes mais
    # "has-text-right", entao so pegar a primeira ocorrencia em ordem de
    # documento distingue as duas sem depender de nth-of-type (que conta
    # entre irmaos do MESMO pai - a tag <p> da liga fica dentro de uma
    # <div> aninhada junto do icone da bandeira, nao e irma direta da
    # <p> de data/hora).
    primeira_coluna = linha.select_one(".column.is-size-7")
    home_el = linha.select_one("p.home")
    away_el = linha.select_one("p.away")
    percentual_el = linha.select_one(".stats-val")
    view_match_links = [a for a in linha.select("a[href]") if a.get_text(strip=True) == "View Match"]

    if primeira_coluna is None or home_el is None or away_el is None or percentual_el is None or not view_match_links:
        # Entrada malformada (payload sem contrato de estabilidade, ver
        # a mesma politica ja usada em app/sda.py/app/espn_summary.py) -
        # nao derruba as demais linhas da pagina.
        return None

    ps_primeira_coluna = primeira_coluna.select("p")
    if not ps_primeira_coluna:
        return None
    kickoff_texto = ps_primeira_coluna[0].get_text(strip=True)
    liga_texto = ps_primeira_coluna[1].get_text(strip=True) if len(ps_primeira_coluna) > 1 else None

    match_url = view_match_links[0]["href"]
    match_id = match_url.rstrip("/").rsplit("/", 1)[-1]
    if not match_id:
        return None

    percentual_texto = percentual_el.get_text(strip=True).rstrip("%")
    try:
        percentual = float(percentual_texto)
    except ValueError:
        return None

    return ApwinEntrada(
        match_id=match_id,
        match_url=match_url,
        kickoff_brt_texto=kickoff_texto,
        kickoff_utc=_combinar_data_hora(kickoff_texto),
        liga_texto=liga_texto,
        time_casa_texto=home_el.get_text(strip=True),
        time_fora_texto=away_el.get_text(strip=True),
        percentual=percentual,
    )


def montar_texto_bruto(entrada: ApwinEntrada, pagina: PaginaMercado) -> str:
    linha_texto = f", linha {pagina.linha}" if pagina.linha is not None else ""
    return (
        f"{entrada.time_casa_texto} x {entrada.time_fora_texto} ({entrada.liga_texto or '?'})\n"
        f"Kickoff: {entrada.kickoff_brt_texto} BRT\n"
        f"APWin decreasing stats: {pagina.mercado} {pagina.selecao}{linha_texto} - {entrada.percentual}% "
        f"(ultimos jogos)"
    )
