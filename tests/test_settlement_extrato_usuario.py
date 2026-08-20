from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal

from app.settlement.banca import Aposta, EntradaLedger
from app.settlement.extrato_usuario import (
    buscar_config_banca,
    buscar_entradas_elegiveis,
    buscar_periodos_assinatura,
    gravar_extrato,
    reconstruir_extrato_usuario,
)
from tests._fakes import FakeCursor


@dataclass
class _SettingsFake:
    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"


def test_buscar_entradas_elegiveis_mapeia_colunas():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[[("p1", "fix-1", kickoff, Decimal("1.85"), "green", Decimal("1.85"), "msg-1")]]
    )

    entradas = buscar_entradas_elegiveis(cur, "u1")

    assert entradas == [
        EntradaLedger(
            pick_id="p1", fixture_id="fix-1", kickoff_utc=kickoff, odd=Decimal("1.85"),
            resultado="green", fator_retorno=Decimal("1.85"), message_id="msg-1",
        )
    ]
    assert cur.queries[0][1] == ("u1",)


def test_buscar_periodos_assinatura_mapeia_colunas():
    cur = FakeCursor(fetchall_results=[[(date(2026, 8, 1), date(2026, 8, 31))]])

    assert buscar_periodos_assinatura(cur, "u1") == [(date(2026, 8, 1), date(2026, 8, 31))]


def test_buscar_config_banca_usa_linha_existente():
    cur = FakeCursor(fetchone_results=[(Decimal("2000"), Decimal("0.05"), "proporcional")])

    resultado = buscar_config_banca(cur, "u1", _SettingsFake())

    assert resultado == (Decimal("2000"), Decimal("0.05"), "proporcional")


def test_buscar_config_banca_sem_linha_usa_default_das_settings():
    cur = FakeCursor(fetchone_results=[None])

    resultado = buscar_config_banca(cur, "u1", _SettingsFake(banca_inicial_padrao=1500, stake_pct_padrao=0.03))

    assert resultado == (Decimal("1500"), Decimal("0.03"), "fixo")


def test_gravar_extrato_apaga_e_reinsere():
    aposta = Aposta(
        pick_id="p1", fixture_id="fix-1", message_id="msg-1", odd=Decimal("1.85"),
        stake_valor=Decimal("20.00"), stake_pct=Decimal("0.02"), resultado="green",
        retorno=Decimal("37.00"), banca_antes=Decimal("1000"), banca_depois=Decimal("1017.00"), sequencia=1,
    )
    cur = FakeCursor()

    gravar_extrato(cur, "u1", [aposta])

    assert cur.queries[0] == ("delete from bets where user_id = %s::uuid", ("u1",))
    insert_sql, params = cur.queries[1]
    assert "insert into bets" in insert_sql
    assert params[0] == "u1" and params[2] == "p1" and params[-1] == 1


def test_reconstruir_extrato_usuario_orquestra_tudo():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", kickoff, Decimal("2.0"), "green", Decimal("2.0"), "msg-1")],  # entradas elegiveis
            [(date(2026, 8, 1), date(2026, 8, 31))],  # periodos
        ],
        fetchone_results=[None],  # sem user_bankroll_config -> default
    )

    total = reconstruir_extrato_usuario(cur, "u1", _SettingsFake())

    assert total == 1
    # delete + 1 insert gravados depois das 3 leituras
    assert cur.queries[-2][0] == "delete from bets where user_id = %s::uuid"
    assert "insert into bets" in cur.queries[-1][0]


def test_reconstruir_extrato_usuario_fora_do_periodo_nao_grava_nada():
    kickoff = datetime(2026, 1, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(
        fetchall_results=[
            [("p1", "fix-1", kickoff, Decimal("2.0"), "green", Decimal("2.0"), "msg-1")],
            [(date(2026, 8, 1), date(2026, 8, 31))],  # assinatura so cobre agosto
        ],
        fetchone_results=[None],
    )

    total = reconstruir_extrato_usuario(cur, "u1", _SettingsFake())

    assert total == 0
    assert cur.queries[-1][0] == "delete from bets where user_id = %s::uuid"
