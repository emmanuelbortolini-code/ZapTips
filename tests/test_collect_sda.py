from datetime import datetime, timezone

import httpx

from app.sda import SdaCard
from scripts.collect_sda import (
    buscar_cards_backfill,
    buscar_cards_recorrente,
    buscar_urls_ja_coletadas,
    calcular_hash_conteudo,
    upsert_raw_pick,
)
from tests._fakes import FakeCursor

# upsert_source e compartilhado (app/sources.py) - testado em
# tests/test_sources.py, nao duplicado aqui.


def _card(url="https://x.com/a", status="ativo", dias_atras=0, tipster="Fulano") -> SdaCard:
    publicado_em = datetime.now(timezone.utc)
    if dias_atras:
        from datetime import timedelta

        publicado_em = publicado_em - timedelta(days=dias_atras)
    return SdaCard(
        url=url, status=status, titulo="Palpite A x B", tipster=tipster, tipster_url=None,
        data="09.08.2026", hora="11:00", oneliner="Mais 2.5 gols, - odds 1.82", casa="Superbet",
        publicado_em=publicado_em,
    )


def test_calcular_hash_conteudo_e_deterministico():
    card = _card()
    h1 = calcular_hash_conteudo(card, "texto")
    h2 = calcular_hash_conteudo(card, "texto")

    assert h1 == h2
    assert len(h1) == 64


def test_calcular_hash_conteudo_muda_se_url_mudar():
    assert calcular_hash_conteudo(_card(url="https://x.com/a"), "texto") != calcular_hash_conteudo(
        _card(url="https://x.com/b"), "texto"
    )


def test_upsert_raw_pick_novo_usa_so_o_insert():
    cur = FakeCursor(fetchone_results=[("pick-id",)])

    pick_id, novo = upsert_raw_pick(cur, "source-1", _card(), "texto", "hash-abc")

    assert pick_id == "pick-id"
    assert novo is True
    assert len(cur.queries) == 1


def test_upsert_raw_pick_existente_cai_para_select():
    cur = FakeCursor(fetchone_results=[None, ("pick-id-existente",)])

    pick_id, novo = upsert_raw_pick(cur, "source-1", _card(), "texto", "hash-abc")

    assert pick_id == "pick-id-existente"
    assert novo is False


def test_buscar_urls_ja_coletadas_ignora_url_nula():
    cur = FakeCursor(fetchall_results=[[("https://x.com/a",), (None,)]])

    urls = buscar_urls_ja_coletadas(cur, "source-1")

    assert urls == {"https://x.com/a"}


def test_buscar_cards_recorrente_para_quando_pagina_nao_traz_card_novo(monkeypatch):
    paginas = iter(
        [
            [_card(url="https://x.com/novo1"), _card(url="https://x.com/ja-visto")],
            [_card(url="https://x.com/ja-visto")],  # nada novo -> para
        ]
    )
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", lambda *a, **kw: "html")
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_RECORRENTE_SEGUNDOS", 0)

    resultado = buscar_cards_recorrente(client=None, urls_conhecidas={"https://x.com/ja-visto"})

    assert [c.url for c in resultado] == ["https://x.com/novo1"]


def test_buscar_cards_recorrente_ignora_cards_encerrados(monkeypatch):
    paginas = iter(
        [
            [_card(url="https://x.com/a", status="ativo"), _card(url="https://x.com/b", status="encerrado")],
            [],  # pagina seguinte sem nada novo -> para
        ]
    )
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", lambda *a, **kw: "html")
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_RECORRENTE_SEGUNDOS", 0)

    resultado = buscar_cards_recorrente(client=None, urls_conhecidas=set())

    assert [c.url for c in resultado] == ["https://x.com/a"]


def test_buscar_cards_backfill_para_no_corte_de_data(monkeypatch):
    paginas = iter(
        [
            [_card(url="https://x.com/a", status="encerrado", dias_atras=10)],
            [_card(url="https://x.com/b", status="encerrado", dias_atras=100)],
        ]
    )
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", lambda *a, **kw: "html")
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_BACKFILL_SEGUNDOS", 0)

    resultado = buscar_cards_backfill(client=None)

    # 2 paginas buscadas (a 2a tem card > 90 dias, entao para APOS
    # coleta-la) - se tentasse uma 3a, next(paginas) levantaria StopIteration.
    assert [c.url for c in resultado] == ["https://x.com/a", "https://x.com/b"]


def test_buscar_cards_backfill_pagina_sem_data_parseavel_nao_para_sozinha(monkeypatch):
    # Card sem data (ou malformada) tem publicado_em=None - uma pagina
    # inteira assim nao aciona o corte por data (documentado, nao e bug),
    # entao a paginacao continua ate achar uma pagina com data real.
    sem_data = SdaCard(
        url="https://x.com/sem-data", status="encerrado", titulo="Palpite sem data",
        tipster=None, tipster_url=None, data=None, hora=None, oneliner=None, casa=None,
        publicado_em=None,
    )
    paginas = iter(
        [
            [sem_data],
            [_card(url="https://x.com/com-data", status="encerrado", dias_atras=100)],
        ]
    )
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", lambda *a, **kw: "html")
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_BACKFILL_SEGUNDOS", 0)

    resultado = buscar_cards_backfill(client=None)

    assert [c.url for c in resultado] == ["https://x.com/sem-data", "https://x.com/com-data"]


def test_buscar_cards_backfill_ignora_cards_ativos(monkeypatch):
    paginas = iter([[_card(url="https://x.com/a", status="ativo", dias_atras=10)]])
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", lambda *a, **kw: "html")
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_BACKFILL_SEGUNDOS", 0)

    resultado = buscar_cards_backfill(client=None)

    assert resultado == []


def test_buscar_cards_falha_de_rede_preserva_paginas_ja_buscadas(monkeypatch):
    chamadas = {"n": 0}

    def fetch_com_falha(*a, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            request = httpx.Request("GET", "https://x.com")
            raise httpx.ConnectTimeout("timeout", request=request)
        return "html"

    paginas = iter([[_card(url="https://x.com/a", status="ativo")]])
    monkeypatch.setattr("scripts.collect_sda.fetch_listing_page", fetch_com_falha)
    monkeypatch.setattr("scripts.collect_sda.parse_listing_page", lambda html: next(paginas))
    monkeypatch.setattr("scripts.collect_sda.RATE_LIMIT_RECORRENTE_SEGUNDOS", 0)

    resultado = buscar_cards_recorrente(client=None, urls_conhecidas=set())

    assert [c.url for c in resultado] == ["https://x.com/a"]
