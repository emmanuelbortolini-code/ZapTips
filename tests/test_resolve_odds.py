from app.odds_resolution import PickParaResolverOdds
from scripts.resolve_odds import (
    aplicar_resolucao,
    buscar_picks_vinculados,
    carregar_casas_licenciadas,
    carregar_odds_referencia,
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
