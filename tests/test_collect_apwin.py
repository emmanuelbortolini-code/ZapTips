from datetime import datetime, timezone

from app.apwin import ApwinEntrada, PAGINAS
from app.matcher import TeamAlias
from scripts.collect_apwin import (
    calcular_hash_conteudo,
    carregar_aliases_relevantes,
    carregar_fixtures_escopo,
    inserir_pick,
    resolver_fixture_id,
    upsert_raw_pick,
)
from tests._fakes import FakeCursor

_PAGINA_OVER_UNDER = next(p for p in PAGINAS if p.mercado == "over_under")


def _entrada(casa="Palmeiras", fora="Corinthians", kickoff=None, match_url="https://www.apwin.com/match/a/id1/"):
    return ApwinEntrada(
        match_id="id1", match_url=match_url,
        kickoff_brt_texto="25/08/2026 20:45", kickoff_utc=kickoff,
        liga_texto="Brasileirao Serie A", time_casa_texto=casa, time_fora_texto=fora,
        percentual=100.0,
    )


def _alias(team_id, texto):
    return TeamAlias(team_id=team_id, alias_normalizado=texto.lower())


# --- resolver_fixture_id -----------------------------------------------------------


def test_resolve_fixture_unica_candidata():
    aliases = [_alias("t1", "Palmeiras"), _alias("t2", "Corinthians")]
    fixtures = [("t1", "t2", "fx-1", None)]
    assert resolver_fixture_id(_entrada(), aliases, fixtures) == "fx-1"


def test_resolve_none_quando_time_nao_bate():
    aliases = [_alias("t1", "Palmeiras")]
    fixtures = [("t1", "t2", "fx-1", None)]
    assert resolver_fixture_id(_entrada(fora="TimeQualquerDesconhecido"), aliases, fixtures) is None


def test_resolve_none_quando_ambiguo_sem_kickoff_pra_desempatar():
    aliases = [_alias("t1", "Palmeiras"), _alias("t2", "Corinthians")]
    fixtures = [("t1", "t2", "fx-ida", None), ("t1", "t2", "fx-volta", None)]
    assert resolver_fixture_id(_entrada(kickoff=None), aliases, fixtures) is None


def test_resolve_desempata_por_kickoff_mais_proximo():
    aliases = [_alias("t1", "Palmeiras"), _alias("t2", "Corinthians")]
    alvo = datetime(2026, 8, 25, 20, 0, tzinfo=timezone.utc)
    fixtures = [
        ("t1", "t2", "fx-longe", datetime(2026, 3, 1, tzinfo=timezone.utc)),
        ("t1", "t2", "fx-perto", datetime(2026, 8, 25, 19, 0, tzinfo=timezone.utc)),
    ]
    assert resolver_fixture_id(_entrada(kickoff=alvo), aliases, fixtures) == "fx-perto"


def test_resolve_none_sem_nenhuma_fixture_candidata():
    aliases = [_alias("t1", "Palmeiras"), _alias("t2", "Corinthians")]
    assert resolver_fixture_id(_entrada(), aliases, []) is None


# --- carregar_fixtures_escopo / carregar_aliases_relevantes ------------------------


def test_carregar_fixtures_escopo_filtra_por_liga():
    cur = FakeCursor(fetchall_results=[[("t1", "t2", "fx-1", None)]])
    fixtures = carregar_fixtures_escopo(cur)
    assert fixtures == [("t1", "t2", "fx-1", None)]
    sql, params = cur.queries[0]
    assert "liga = any(" in sql
    assert params == (["bra.1", "bra.2"],)


def test_carregar_aliases_relevantes_filtra_so_times_com_fixture():
    fixtures = [("t1", "t2", "fx-1", None)]
    cur = FakeCursor(fetchall_results=[[("t1", "palmeiras"), ("t2", "corinthians"), ("t3", "outrotime")]])
    aliases = carregar_aliases_relevantes(cur, fixtures)
    assert {a.team_id for a in aliases} == {"t1", "t2"}


# --- calcular_hash_conteudo ---------------------------------------------------------


def test_hash_conteudo_deterministico_e_sensivel_a_mercado():
    entrada = _entrada()
    hash_a = calcular_hash_conteudo(entrada, _PAGINA_OVER_UNDER, "texto")
    hash_b = calcular_hash_conteudo(entrada, _PAGINA_OVER_UNDER, "texto")
    assert hash_a == hash_b

    pagina_btts = next(p for p in PAGINAS if p.mercado == "ambas_marcam")
    hash_c = calcular_hash_conteudo(entrada, pagina_btts, "texto")
    assert hash_c != hash_a


# --- upsert_raw_pick / inserir_pick --------------------------------------------------


def test_upsert_raw_pick_novo_marca_extraido_em_na_hora():
    cur = FakeCursor(fetchone_results=[("raw-1",)])
    raw_pick_id, novo = upsert_raw_pick(cur, "source-1", _entrada(), "texto", "hash-1")
    assert (raw_pick_id, novo) == ("raw-1", True)
    sql, params = cur.queries[0]
    assert "extraido_em" in sql and "now()" in sql
    assert "on conflict (hash_conteudo) do nothing" in sql


def test_upsert_raw_pick_existente_busca_id_sem_duplicar():
    cur = FakeCursor(fetchone_results=[None, ("raw-existente",)])
    raw_pick_id, novo = upsert_raw_pick(cur, "source-1", _entrada(), "texto", "hash-1")
    assert (raw_pick_id, novo) == ("raw-existente", False)


def test_inserir_pick_grava_status_vinculado_e_stat_fonte():
    cur = FakeCursor()
    inserir_pick(cur, "raw-1", _entrada(), _PAGINA_OVER_UNDER, "fx-1")
    sql, params = cur.queries[0]
    assert "'vinculado'" in sql
    assert "stat_fonte" in sql and "stat_fonte_tipo" in sql
    assert 100.0 in params
    assert "frequencia_ultimos_jogos" in params
