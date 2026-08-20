from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from app.resumo_semanal_generator import (
    buscar_usuarios_com_atividade_na_semana,
    gerar_resumos_semanais,
    montar_idempotency_key_resumo_semanal,
    montar_janela_semana,
)
from app.messages_generator import montar_idempotency_key
from app.fechamento_generator import montar_idempotency_key_fechamento
from tests._fakes import FakeCursor

_RODAPE = "18+. Aposte com responsabilidade. Responda SAIR pra cancelar."


@dataclass
class _SettingsFake:
    banca_inicial_padrao: float = 1000
    stake_pct_padrao: float = 0.02
    stake_modo_padrao: str = "fixo"


def test_montar_janela_semana_cobre_segunda_a_domingo():
    janela = montar_janela_semana(date(2026, 8, 10))
    assert janela.inicio_utc.date() == date(2026, 8, 10)
    # fim exclusivo = inicio da segunda SEGUINTE (17/08).
    assert janela.fim_utc.date() == date(2026, 8, 17)


def test_montar_idempotency_key_resumo_semanal_e_deterministico():
    a = montar_idempotency_key_resumo_semanal("u1", date(2026, 8, 10))
    b = montar_idempotency_key_resumo_semanal("u1", date(2026, 8, 10))
    assert a == b


def test_montar_idempotency_key_resumo_semanal_nunca_colide_com_palpite_ou_fechamento():
    resumo = montar_idempotency_key_resumo_semanal("u1", date(2026, 8, 10))
    palpite = montar_idempotency_key("u1", "f1", date(2026, 8, 10))
    fechamento = montar_idempotency_key_fechamento("u1", "f1", date(2026, 8, 10))
    assert resumo != palpite
    assert resumo != fechamento


def test_buscar_usuarios_com_atividade_na_semana():
    cur = FakeCursor(fetchall_results=[[("u1",), ("u2",)]])
    janela = montar_janela_semana(date(2026, 8, 10))

    assert buscar_usuarios_com_atividade_na_semana(cur, janela) == ["u1", "u2"]


def test_gerar_resumos_semanais_grava_mensagem_sem_fixture():
    cur = FakeCursor(
        fetchall_results=[
            [("u1",)],  # usuarios com atividade
            [
                ("p1", "fix-1", "msg-1", Decimal("2.0"), Decimal("20.00"), Decimal("0.02"),
                 "green", Decimal("40.00"), Decimal("1000.00"), Decimal("1020.00"), 1),
            ],  # apostas da semana
        ],
        fetchone_results=[
            None,  # banca antes da semana: nenhuma aposta anterior
            None,  # buscar_config_banca: sem user_bankroll_config -> default
            (0,),  # nao liquidados da semana
            ("Emmanuel",),  # nome do usuario
            ("msg-nova",),  # insert retornou id
        ],
    )

    total = gerar_resumos_semanais(cur, date(2026, 8, 10), _RODAPE, _SettingsFake())

    assert total == 1
    insert_sql, params = cur.queries[-1]
    assert "insert into messages" in insert_sql
    assert "'resumo_semanal'" in insert_sql
    assert "on conflict (idempotency_key) do nothing" in insert_sql
    user_id, pick_ids, corpo, idempotency_key = params
    assert user_id == "u1" and pick_ids == ["p1"]
    assert "Banca simulada" in corpo
    assert "1 palpites, 1 greens e 0 reds" in corpo


def test_gerar_resumos_semanais_idempotente_nao_conta_conflito():
    cur = FakeCursor(
        fetchall_results=[
            [("u1",)],
            [
                ("p1", "fix-1", "msg-1", Decimal("2.0"), Decimal("20.00"), Decimal("0.02"),
                 "green", Decimal("40.00"), Decimal("1000.00"), Decimal("1020.00"), 1),
            ],
        ],
        fetchone_results=[None, None, (0,), ("Emmanuel",), None],  # insert nao retorna id
    )

    total = gerar_resumos_semanais(cur, date(2026, 8, 10), _RODAPE, _SettingsFake())

    assert total == 0


def test_gerar_resumos_semanais_sem_usuarios_com_atividade():
    cur = FakeCursor(fetchall_results=[[]])
    assert gerar_resumos_semanais(cur, date(2026, 8, 10), _RODAPE, _SettingsFake()) == 0


def test_gerar_resumos_semanais_usa_banca_da_ultima_aposta_anterior_a_semana_quando_existir():
    cur = FakeCursor(
        fetchall_results=[
            [("u1",)],
            [
                ("p1", "fix-1", "msg-1", Decimal("2.0"), Decimal("20.00"), Decimal("0.02"),
                 "green", Decimal("40.00"), Decimal("1050.00"), Decimal("1070.00"), 3),
            ],
        ],
        fetchone_results=[
            (Decimal("1050.00"),),  # banca_depois da ultima aposta ANTES da semana
            (0,),  # nao liquidados
            ("Emmanuel",),
            ("msg-nova",),
        ],
    )

    gerar_resumos_semanais(cur, date(2026, 8, 10), _RODAPE, _SettingsFake())

    _, params = cur.queries[-1]
    corpo = params[2]
    assert "R$ 1050.00 -> R$ 1070.00" in corpo
