from app.odds_resolution import OddReferenciaEncontrada, PickParaResolverOdds
from scripts.resolve_odds import (
    aplicar_resolucao,
    buscar_picks_vinculados,
    carregar_casas_licenciadas,
    carregar_fixtures_espn,
    carregar_nomes_casas_licenciadas,
    carregar_odds_referencia,
    picks_candidatos_a_espn,
)
from tests._fakes import FakeCursor

# upsert_pick_orfao e compartilhado (app/picks_orfaos.py) - testado em
# tests/test_picks_orfaos.py, nao duplicado aqui.


def _pick(**overrides) -> PickParaResolverOdds:
    base = dict(
        pick_id="p1", fixture_id="fix-1", mercado="1x2", selecao="Home win",
        time_casa="Goiás", time_fora="Londrina", casa_id=None, odd_citada=None,
    )
    base.update(overrides)
    return PickParaResolverOdds(**base)


def test_buscar_picks_vinculados_mapeia_colunas_e_filtra_status():
    cur = FakeCursor(
        fetchall_results=[[("p1", "fix-1", "1x2", "Home win", "Goiás", "Londrina", "casa-1", 1.85)]]
    )

    picks = buscar_picks_vinculados(cur)

    assert picks == [
        PickParaResolverOdds(
            pick_id="p1", fixture_id="fix-1", mercado="1x2", selecao="Home win",
            time_casa="Goiás", time_fora="Londrina", casa_id="casa-1", odd_citada=1.85,
        )
    ]
    sql = cur.queries[0][0]
    assert "'vinculado'" in sql and "'sem_odd'" in sql


def test_buscar_picks_vinculados_exclui_odd_de_origem_manual():
    # Achado real: rodar este script depois de um palpite manual
    # (console, criar_palpite_manual) ja aprovado/enviado sobrescrevia a
    # odd que o operador digitou com o valor automatico do OddsPapi -
    # nivel 4 (manual) e "fora de escopo" deste script por design.
    cur = FakeCursor(fetchall_results=[[]])

    buscar_picks_vinculados(cur)

    sql = cur.queries[0][0]
    assert "odd_referencia_origem is null or odd_referencia_origem <> 'manual'" in sql


def test_carregar_casas_licenciadas_filtra_licenciada_br():
    cur = FakeCursor(fetchall_results=[[("casa-1",)]])

    assert carregar_casas_licenciadas(cur) == {"casa-1"}
    assert "licenciada_br = true" in cur.queries[0][0]


def test_carregar_odds_referencia_agrupa_por_chave():
    cur = FakeCursor(fetchall_results=[[("fix-1", "1x2", "casa", 1.90), ("fix-1", "1x2", "casa", 1.75)]])

    odds = carregar_odds_referencia(cur)

    assert odds == {("fix-1", "1x2", "casa"): [1.90, 1.75]}


def test_aplicar_resolucao_sem_odd_marca_status_e_orfao():
    cur = FakeCursor(fetchone_results=[(1,)])
    pick = _pick(selecao="1X")  # dupla chance, nao resolve

    resultado = aplicar_resolucao(cur, pick, casas_licenciadas=set(), odds_por_fixture={}, margem_pct=0.04, odd_minima_absoluta=1.40)

    assert resultado == "sem_odd"
    assert len(cur.queries) == 2
    assert "sem_odd" in cur.queries[0][0]
    assert "insert into picks_orfaos" in cur.queries[1][0]


def test_aplicar_resolucao_abaixo_do_piso_descarta():
    cur = FakeCursor(fetchone_results=[(1,)])
    pick = _pick(casa_id="casa-1", odd_citada=1.20)

    resultado = aplicar_resolucao(
        cur, pick, casas_licenciadas={"casa-1"}, odds_por_fixture={}, margem_pct=0.04, odd_minima_absoluta=1.40
    )

    assert resultado == "descartado"
    assert "descartado" in cur.queries[0][0]
    assert "insert into picks_orfaos" in cur.queries[1][0]


def test_aplicar_resolucao_abaixo_do_piso_ainda_assim_grava_odd_sombra():
    # Fase 6d: "Cada um deles tem odd de referencia e odd minima sombra,
    # capturadas na coleta, entao o ROI e' calculavel para todos" - sem
    # isso, um pick rejeitado pelo piso nunca entraria no relatorio de
    # performance por fonte.
    cur = FakeCursor(fetchone_results=[(1,)])
    pick = _pick(casa_id="casa-1", odd_citada=1.20)

    aplicar_resolucao(
        cur, pick, casas_licenciadas={"casa-1"}, odds_por_fixture={}, margem_pct=0.04, odd_minima_absoluta=1.40
    )

    sql, params = cur.queries[0]
    assert "odd_referencia" in sql and "odd_minima" in sql
    assert params == (1.20, "fonte", 1.40, "p1")


def test_aplicar_resolucao_sucesso_grava_odd_referencia_e_minima():
    cur = FakeCursor()
    pick = _pick(casa_id="casa-1", odd_citada=2.00)

    resultado = aplicar_resolucao(
        cur, pick, casas_licenciadas={"casa-1"}, odds_por_fixture={}, margem_pct=0.04, odd_minima_absoluta=1.40
    )

    assert resultado == "resolvido"
    assert len(cur.queries) == 1
    sql, params = cur.queries[0]
    assert "update picks" in sql
    assert params == (2.00, "fonte", 1.92, "p1")


def test_aplicar_resolucao_usa_odd_espn_quando_niveis_1_2_nao_resolvem():
    # Nivel 3: so entra em jogo quando resolver_odd_referencia (niveis
    # 1/2, sem rede) nao acha nada - odd_espn e' pre-computada pelo
    # chamador (executar(), apos a fase de rede) e passada pronta aqui.
    cur = FakeCursor()
    pick = _pick()  # sem casa_id/odd_citada, sem odds_referencia -> niveis 1/2 vazios
    odd_espn = OddReferenciaEncontrada(valor=1.90, origem="espn")

    resultado = aplicar_resolucao(
        cur, pick, casas_licenciadas=set(), odds_por_fixture={},
        margem_pct=0.04, odd_minima_absoluta=1.40, odd_espn=odd_espn,
    )

    assert resultado == "resolvido"
    sql, params = cur.queries[0]
    assert params == (1.90, "espn", 1.82, "p1")


def test_aplicar_resolucao_nivel_1_2_tem_prioridade_sobre_odd_espn():
    cur = FakeCursor()
    pick = _pick(casa_id="casa-1", odd_citada=2.00)
    odd_espn = OddReferenciaEncontrada(valor=1.50, origem="espn")

    aplicar_resolucao(
        cur, pick, casas_licenciadas={"casa-1"}, odds_por_fixture={},
        margem_pct=0.04, odd_minima_absoluta=1.40, odd_espn=odd_espn,
    )

    sql, params = cur.queries[0]
    assert params == (2.00, "fonte", 1.92, "p1")


def test_carregar_nomes_casas_licenciadas_normaliza():
    cur = FakeCursor(fetchall_results=[[("Bet365",), ("Bet 365",)]])

    nomes = carregar_nomes_casas_licenciadas(cur)

    assert nomes == {"bet365"}
    assert "licenciada_br = true" in cur.queries[0][0]


def test_carregar_fixtures_espn_mapeia_por_id():
    cur = FakeCursor(fetchall_results=[[("fix-1", "401841205", "bra.1")]])

    mapa = carregar_fixtures_espn(cur, {"fix-1"})

    assert mapa == {"fix-1": ("401841205", "bra.1")}


def test_carregar_fixtures_espn_conjunto_vazio_nao_bate_no_banco():
    cur = FakeCursor()

    mapa = carregar_fixtures_espn(cur, set())

    assert mapa == {}
    assert cur.queries == []


def test_picks_candidatos_a_espn_exclui_ja_resolvidos_pelos_niveis_1_2():
    resolvido_nivel1 = _pick(pick_id="p1", casa_id="casa-1", odd_citada=1.85)
    nao_resolvido = _pick(pick_id="p2", fixture_id="fix-2")

    candidatos = picks_candidatos_a_espn(
        [resolvido_nivel1, nao_resolvido], casas_licenciadas={"casa-1"}, odds_por_fixture={}
    )

    assert [p.pick_id for p in candidatos] == ["p2"]


def test_picks_candidatos_a_espn_exclui_mercado_fora_do_1x2():
    pick = _pick(pick_id="p1", mercado="over_under", selecao="Under 2.5")

    candidatos = picks_candidatos_a_espn([pick], casas_licenciadas=set(), odds_por_fixture={})

    assert candidatos == []


def test_picks_candidatos_a_espn_exclui_selecao_ambigua():
    pick = _pick(pick_id="p1", mercado="1x2", selecao="1X")  # dupla chance

    candidatos = picks_candidatos_a_espn([pick], casas_licenciadas=set(), odds_por_fixture={})

    assert candidatos == []
