from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.relatorio_publico import (
    buscar_entradas_mestre,
    contar_nao_liquidados_mestre,
    gerar_dados_publicos,
)
from app.settlement.banca import EntradaLedger
from app.settlement.metricas_publicas import NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO
from tests._fakes import FakeCursor


@dataclass
class _SettingsFake:
    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"


def test_buscar_entradas_mestre_mapeia_colunas():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", kickoff, Decimal("1.85"), "green", Decimal("1.85"))]
        ]
    )

    entradas = buscar_entradas_mestre(cur)

    assert entradas == [
        EntradaLedger(
            pick_id="p1", fixture_id="fix-1", kickoff_utc=kickoff, odd=Decimal("1.85"),
            resultado="green", fator_retorno=Decimal("1.85"),
        )
    ]


def test_contar_nao_liquidados_mestre():
    cur = FakeCursor(fetchone_results=[(4,)])
    assert contar_nao_liquidados_mestre(cur, None) == 4
    assert cur.queries[0][1] == (None, None)


def test_gerar_dados_publicos_orquestra_tudo():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", kickoff, Decimal("2.0"), "green", Decimal("2.0"))],  # entradas mestre
        ],
        fetchone_results=[(0,), (0,), (0,)],  # nao liquidados: 7d, 30d, desde o inicio
    )
    agora = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)

    dados = gerar_dados_publicos(cur, _SettingsFake(), agora)

    assert dados.banca_inicial == Decimal("1000")
    assert dados.gerado_em == agora
    assert dados.curva_banca == ((None, Decimal("1000")), (kickoff, Decimal("1020.0000")))
    nomes = [p.nome for p in dados.periodos]
    assert nomes == [NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO]
    desde_o_inicio = next(p for p in dados.periodos if p.nome == NOME_DESDE_O_INICIO)
    assert desde_o_inicio.metricas.apostas_no_periodo == 1
    assert desde_o_inicio.metricas.banca_atual == Decimal("1020.0000")
