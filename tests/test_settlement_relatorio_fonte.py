from datetime import datetime, timezone
from decimal import Decimal

from app.settlement.relatorio_fonte import (
    agrupar,
    buscar_picks_com_odd,
    buscar_quarentena_por_fonte,
    buscar_volume_sem_odd,
    gerar_relatorio_por_fonte,
    gerar_relatorio_por_fonte_e_mercado,
    gerar_relatorio_por_fonte_e_tipster,
)
from tests._fakes import FakeCursor


def test_buscar_picks_com_odd_mapeia_colunas_e_trata_nao_liquidavel_como_nao_liquidado():
    cur = FakeCursor(
        fetchall_results=[
            [
                ("p1", "Eagle Predict", "Tipster A", "1x2", "green", Decimal("1.85"), Decimal("1.90"), Decimal("1.88")),
                ("p2", "Eagle Predict", "Tipster A", "1x2", "nao_liquidavel", Decimal("1.50"), None, None),
                ("p3", "Eagle Predict", "Tipster A", "1x2", None, Decimal("1.60"), None, None),
            ]
        ]
    )

    linhas = buscar_picks_com_odd(cur)

    assert linhas[0][3].resultado == "green"
    assert linhas[1][3].resultado is None  # nao_liquidavel -> None
    assert linhas[2][3].resultado is None  # nunca liquidado -> None
    sql = cur.queries[0][0]
    assert "'vinculado'" in sql and "'descartado'" in sql and "'encerrada'" in sql


def test_buscar_picks_com_odd_passa_desde_para_a_query():
    cur = FakeCursor(fetchall_results=[[]])
    desde = datetime(2026, 7, 1, tzinfo=timezone.utc)

    buscar_picks_com_odd(cur, desde)

    assert cur.queries[0][1] == (desde, desde)


def test_buscar_volume_sem_odd_mapeia_colunas():
    cur = FakeCursor(fetchall_results=[[("Eagle Predict", "Tipster A", "1x2", 5)]])
    assert buscar_volume_sem_odd(cur) == [("Eagle Predict", "Tipster A", "1x2", 5)]
    assert "'sem_odd'" in cur.queries[0][0]


def test_buscar_quarentena_por_fonte():
    cur = FakeCursor(fetchall_results=[[("Eagle Predict", True), ("SDA", False)]])
    assert buscar_quarentena_por_fonte(cur) == {"Eagle Predict": True, "SDA": False}


# --- agrupar: sem_odd nao vaza volume entre sub-grupos ------------------------------


def _linha(fonte, tipster, mercado, resultado, odd=2.0):
    from app.settlement.performance_fonte import PickComOdd

    pick = PickComOdd(pick_id="p", resultado=resultado, odd_minima=Decimal(str(odd)), odd_citada=None, odd_referencia=None)
    return (fonte, tipster, mercado, pick)


def test_agrupar_por_fonte_soma_sem_odd_de_todos_os_mercados():
    linhas = [_linha("F1", "T1", "1x2", "green"), _linha("F1", "T1", "over_under", "red")]
    sem_odd = [("F1", "T1", "1x2", 3), ("F1", "T1", "over_under", 2)]

    grupos = agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte,))

    assert len(grupos) == 1
    assert grupos[0].volume_sem_odd == 5  # 3 + 2, nao duplicado


def test_agrupar_por_fonte_e_mercado_nao_duplica_sem_odd_entre_mercados():
    # Achado real ao projetar o modulo: sem essa granularidade, os dois
    # sub-grupos (1x2 e over_under) mostrariam o volume sem_odd TOTAL da
    # fonte (5) cada um, inflando o total combinado pra 10.
    linhas = [_linha("F1", "T1", "1x2", "green"), _linha("F1", "T1", "over_under", "red")]
    sem_odd = [("F1", "T1", "1x2", 3), ("F1", "T1", "over_under", 2)]

    grupos = agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte, mercado))

    por_mercado = {g.chave: g.volume_sem_odd for g in grupos}
    assert por_mercado[("F1", "1x2")] == 3
    assert por_mercado[("F1", "over_under")] == 2


def test_agrupar_grupo_que_so_existe_em_sem_odd_ainda_aparece():
    linhas = [_linha("F1", "T1", "1x2", "green")]
    sem_odd = [("F1", "T1", "handicap", 4)]  # mercado sem NENHUM pick com odd resolvida

    grupos = agrupar(linhas, sem_odd, lambda fonte, tipster, mercado: (fonte, mercado))

    chaves = {g.chave for g in grupos}
    assert ("F1", "handicap") in chaves
    grupo_handicap = next(g for g in grupos if g.chave == ("F1", "handicap"))
    assert grupo_handicap.volume_sem_odd == 4
    assert grupo_handicap.volume_liquidado == 0
    assert grupo_handicap.roi is None


# --- integracao com FakeCursor -------------------------------------------------------


def test_gerar_relatorio_por_fonte_orquestra_tudo():
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "Eagle Predict", "T1", "1x2", "green", Decimal("2.0"), None, None)],  # picks_com_odd
            [("Eagle Predict", "T1", "1x2", 2)],  # sem_odd
        ]
    )

    grupos = gerar_relatorio_por_fonte(cur)

    assert len(grupos) == 1
    assert grupos[0].chave == ("Eagle Predict",)
    assert grupos[0].volume_liquidado == 1
    assert grupos[0].volume_sem_odd == 2


def test_gerar_relatorio_por_fonte_e_mercado_orquestra_tudo():
    cur = FakeCursor(
        fetchall_results=[
            [
                ("p1", "Eagle Predict", "T1", "1x2", "green", Decimal("2.0"), None, None),
                ("p2", "Eagle Predict", "T1", "over_under", "red", Decimal("1.8"), None, None),
            ],
            [],
        ]
    )

    grupos = gerar_relatorio_por_fonte_e_mercado(cur)

    chaves = {g.chave for g in grupos}
    assert chaves == {("Eagle Predict", "1x2"), ("Eagle Predict", "over_under")}


def test_gerar_relatorio_por_fonte_e_tipster_usa_interrogacao_pra_tipster_nulo():
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "Eagle Predict", None, "1x2", "green", Decimal("2.0"), None, None)],
            [],
        ]
    )

    grupos = gerar_relatorio_por_fonte_e_tipster(cur)

    assert grupos[0].chave == ("Eagle Predict", "?")
