from datetime import datetime, timezone

import httpx

from app.eagle_predict import TelegramPost
from scripts.collect_eagle_predict import (
    buscar_posts,
    buscar_ultimo_id_coletado,
    calcular_hash_conteudo,
    upsert_raw_pick,
)
from tests._fakes import FakeCursor

# upsert_source e compartilhado (app/sources.py) - testado em
# tests/test_sources.py, nao duplicado aqui.

_POST = TelegramPost(
    message_id="100",
    url="https://t.me/eaglepredict/100",
    published_at=datetime(2026, 8, 3, 4, 40, 6, tzinfo=timezone.utc),
    texto="Odds @1.25 on BETANO",
)


def test_calcular_hash_conteudo_e_deterministico():
    hash1 = calcular_hash_conteudo("eaglepredict", _POST)
    hash2 = calcular_hash_conteudo("eaglepredict", _POST)

    assert hash1 == hash2
    assert len(hash1) == 64  # sha256 hex digest


def test_calcular_hash_conteudo_muda_se_texto_mudar():
    post_editado = TelegramPost(
        message_id=_POST.message_id, url=_POST.url, published_at=_POST.published_at,
        texto="texto diferente",
    )

    assert calcular_hash_conteudo("eaglepredict", _POST) != calcular_hash_conteudo("eaglepredict", post_editado)


def test_calcular_hash_conteudo_muda_se_canal_mudar():
    # message_id do Telegram e unico por canal, nao globalmente - dois
    # canais diferentes com o mesmo id numerico e texto nao podem colidir
    # em hash_conteudo (unique em raw_picks inteiro, nao por fonte).
    assert calcular_hash_conteudo("eaglepredict", _POST) != calcular_hash_conteudo("outrocanal", _POST)


def test_upsert_raw_pick_novo_usa_so_o_insert():
    cur = FakeCursor(fetchone_results=[("pick-id",)])

    pick_id, novo = upsert_raw_pick(cur, "source-1", _POST, "hash-abc")

    assert pick_id == "pick-id"
    assert novo is True
    assert len(cur.queries) == 1
    assert "insert into raw_picks" in cur.queries[0][0]


def test_upsert_raw_pick_existente_cai_para_select_apos_conflito():
    cur = FakeCursor(fetchone_results=[None, ("pick-id-existente",)])

    pick_id, novo = upsert_raw_pick(cur, "source-1", _POST, "hash-abc")

    assert pick_id == "pick-id-existente"
    assert novo is False
    assert len(cur.queries) == 2
    assert "select id from raw_picks" in cur.queries[1][0]


def test_buscar_ultimo_id_coletado_extrai_id_da_url():
    cur = FakeCursor(fetchone_results=[("https://t.me/eaglepredict/5647",)])

    assert buscar_ultimo_id_coletado(cur, "source-1") == "5647"


def test_buscar_ultimo_id_coletado_sem_historico_retorna_none():
    cur = FakeCursor(fetchone_results=[None])

    assert buscar_ultimo_id_coletado(cur, "source-1") is None


def _post(msg_id: str, dia: int, mes: int = 8) -> TelegramPost:
    return TelegramPost(
        message_id=msg_id, url=f"https://t.me/eaglepredict/{msg_id}",
        published_at=datetime(2026, mes, dia, tzinfo=timezone.utc), texto="t",
    )


def test_buscar_posts_backfill_para_no_corte_de_data(monkeypatch):
    paginas = iter(
        [
            [_post("300", 5), _post("299", 4)],
            [_post("250", 1, mes=5)],
        ]
    )
    monkeypatch.setattr(
        "scripts.collect_eagle_predict.fetch_channel_page", lambda *a, **kw: "html"
    )
    monkeypatch.setattr(
        "scripts.collect_eagle_predict.parse_channel_page", lambda html, canal: next(paginas)
    )
    monkeypatch.setattr("scripts.collect_eagle_predict.RATE_LIMIT_SECONDS", 0)

    resultado = buscar_posts(
        client=None, canal="eaglepredict", parar_antes_de=datetime(2026, 6, 1, tzinfo=timezone.utc)
    )

    # Parou apos a 2a pagina (cujo post mais antigo passa do corte) sem
    # tentar uma 3a - se tentasse, `next(paginas)` levantaria StopIteration.
    assert [p.message_id for p in resultado] == ["300", "299", "250"]


def test_buscar_posts_incremental_para_quando_pagina_vem_incompleta(monkeypatch):
    paginas = iter([[_post("400", 6)]])  # so 1 post, bem menor que TAMANHO_PAGINA
    monkeypatch.setattr(
        "scripts.collect_eagle_predict.fetch_channel_page", lambda *a, **kw: "html"
    )
    monkeypatch.setattr(
        "scripts.collect_eagle_predict.parse_channel_page", lambda html, canal: next(paginas)
    )

    resultado = buscar_posts(client=None, canal="eaglepredict", after="399")

    assert [p.message_id for p in resultado] == ["400"]


def test_buscar_posts_falha_de_rede_no_meio_preserva_paginas_ja_buscadas(monkeypatch):
    # Mesma licao ja aplicada nos coletores da Fase 1: uma falha no meio
    # da paginacao nao pode jogar fora as paginas ja buscadas.
    chamadas = {"n": 0}

    def fetch_com_falha_na_segunda(*a, **kw):
        chamadas["n"] += 1
        if chamadas["n"] == 2:
            request = httpx.Request("GET", "https://t.me/s/eaglepredict")
            raise httpx.ConnectTimeout("timeout", request=request)
        return "html"

    paginas = iter([[_post("300", 5)]])
    monkeypatch.setattr("scripts.collect_eagle_predict.fetch_channel_page", fetch_com_falha_na_segunda)
    monkeypatch.setattr(
        "scripts.collect_eagle_predict.parse_channel_page", lambda html, canal: next(paginas)
    )
    monkeypatch.setattr("scripts.collect_eagle_predict.RATE_LIMIT_SECONDS", 0)

    resultado = buscar_posts(
        client=None, canal="eaglepredict", parar_antes_de=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )

    assert [p.message_id for p in resultado] == ["300"]


def test_buscar_posts_para_no_limite_maximo_de_paginas(monkeypatch):
    contador = {"n": 0}

    def pagina_sempre_recente(html, canal):
        contador["n"] += 1
        return [_post(str(contador["n"]), 5)]  # sempre depois do corte, nunca para sozinho

    monkeypatch.setattr(
        "scripts.collect_eagle_predict.fetch_channel_page", lambda *a, **kw: "html"
    )
    monkeypatch.setattr("scripts.collect_eagle_predict.parse_channel_page", pagina_sempre_recente)
    monkeypatch.setattr("scripts.collect_eagle_predict.PAGINAS_MAXIMAS", 3)
    monkeypatch.setattr("scripts.collect_eagle_predict.RATE_LIMIT_SECONDS", 0)

    resultado = buscar_posts(
        client=None, canal="eaglepredict", parar_antes_de=datetime(2020, 1, 1, tzinfo=timezone.utc)
    )

    assert len(resultado) == 3
