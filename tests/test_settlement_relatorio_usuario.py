from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal

from app.settlement.banca import Aposta
from app.settlement.metricas import ApostaComData
from app.settlement.relatorio_usuario import (
    buscar_apostas_do_usuario,
    contar_nao_liquidados_periodo,
    gerar_relatorio_usuario,
)
from tests._fakes import FakeCursor


@dataclass
class _SettingsFake:
    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"


def test_buscar_apostas_do_usuario_mapeia_colunas():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [
                (
                    "p1", "fix-1", "msg-1", Decimal("1.85"), Decimal("20.00"), Decimal("0.02"),
                    "green", Decimal("37.00"), Decimal("1000.00"), Decimal("1017.00"), 1, kickoff,
                )
            ]
        ]
    )

    apostas = buscar_apostas_do_usuario(cur, "u1")

    assert apostas == [
        ApostaComData(
            aposta=Aposta(
                pick_id="p1", fixture_id="fix-1", message_id="msg-1", odd=Decimal("1.85"),
                stake_valor=Decimal("20.00"), stake_pct=Decimal("0.02"), resultado="green",
                retorno=Decimal("37.00"), banca_antes=Decimal("1000.00"), banca_depois=Decimal("1017.00"),
                sequencia=1,
            ),
            kickoff_utc=kickoff,
        )
    ]
    assert cur.queries[0][1] == ("u1",)


def test_buscar_apostas_do_usuario_message_id_nulo():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [
                (
                    "p1", "fix-1", None, Decimal("1.85"), Decimal("20.00"), Decimal("0.02"),
                    "green", Decimal("37.00"), Decimal("1000.00"), Decimal("1017.00"), 1, kickoff,
                )
            ]
        ]
    )

    (item,) = buscar_apostas_do_usuario(cur, "u1")

    assert item.aposta.message_id is None


def test_contar_nao_liquidados_periodo():
    cur = FakeCursor(fetchone_results=[(3,)])

    assert contar_nao_liquidados_periodo(cur, "u1", None) == 3
    assert cur.queries[0][1] == ("u1", None, None)


def test_gerar_relatorio_usuario_orquestra_tudo():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [
                (
                    "p1", "fix-1", "msg-1", Decimal("2.0"), Decimal("20.00"), Decimal("0.02"),
                    "green", Decimal("40.00"), Decimal("1000.00"), Decimal("1020.00"), 1, kickoff,
                )
            ]
        ],
        fetchone_results=[None, (5,)],  # sem user_bankroll_config -> default; depois, 5 nao liquidados
    )

    metricas = gerar_relatorio_usuario(cur, "u1", None, _SettingsFake())

    assert metricas.banca_atual == Decimal("1020.00")
    assert metricas.nao_liquidados_no_periodo == 5
