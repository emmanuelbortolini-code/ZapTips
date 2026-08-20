from datetime import date
from decimal import Decimal

from app.pipeline import limites_utc_do_dia
from app.relatorio_diario import RelatorioDiario, buscar_relatorio_diario
from tests._fakes import FakeCursor


def test_buscar_relatorio_diario_mapeia_tudo():
    cur = FakeCursor(
        fetchone_results=[(5,), (1,)],  # enviados, opt_outs
        fetchall_results=[
            [("preferencia_odd_min", 2), ("opt_out", 1)],  # pulados_por_motivo
            [("green", 3), ("red", 2), ("nao_liquidavel", 1)],  # liquidados_por_resultado
        ],
    )

    relatorio = buscar_relatorio_diario(cur, date(2026, 8, 12))

    assert relatorio == RelatorioDiario(
        data=date(2026, 8, 12), enviados=5, pulados=3,
        pulados_por_motivo={"preferencia_odd_min": 2, "opt_out": 1},
        opt_outs=1, liquidados=5, liquidados_por_resultado={"green": 3, "red": 2},
        nao_liquidados=1, taxa_nao_liquidados=Decimal("1") / Decimal("6"),
    )


def test_buscar_relatorio_diario_motivo_nulo_vira_sem_motivo():
    cur = FakeCursor(fetchone_results=[(0,), (0,)], fetchall_results=[[(None, 2)], []])

    relatorio = buscar_relatorio_diario(cur, date(2026, 8, 12))

    assert relatorio.pulados_por_motivo == {"sem motivo": 2}
    assert relatorio.pulados == 2


def test_buscar_relatorio_diario_sem_nenhuma_liquidacao_taxa_none():
    cur = FakeCursor(fetchone_results=[(0,), (0,)], fetchall_results=[[], []])

    relatorio = buscar_relatorio_diario(cur, date(2026, 8, 12))

    assert relatorio.liquidados == 0
    assert relatorio.nao_liquidados == 0
    assert relatorio.taxa_nao_liquidados is None


def test_buscar_relatorio_diario_sem_nao_liquidados_taxa_zero():
    cur = FakeCursor(fetchone_results=[(0,), (0,)], fetchall_results=[[], [("green", 4)]])

    relatorio = buscar_relatorio_diario(cur, date(2026, 8, 12))

    assert relatorio.liquidados == 4
    assert relatorio.nao_liquidados == 0
    assert relatorio.taxa_nao_liquidados == Decimal("0")


# --- garante que a leitura real usa o helper de fuso, nao ::date cru
# (o helper em si e testado em tests/test_pipeline.py) ---


def test_buscar_relatorio_diario_usa_limites_utc_nao_date_cru():
    cur = FakeCursor(fetchone_results=[(0,), (0,)], fetchall_results=[[], []])

    buscar_relatorio_diario(cur, date(2026, 8, 12))

    sql_enviados, params_enviados = cur.queries[0]
    assert "enviada_em >= %s and enviada_em < %s" in sql_enviados
    assert params_enviados == limites_utc_do_dia(date(2026, 8, 12))
