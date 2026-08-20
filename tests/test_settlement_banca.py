from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.settlement.banca import (
    EntradaLedger,
    calcular_fator_retorno,
    calcular_taxa_acerto,
    filtrar_por_periodos_assinatura,
    ordenar_deterministico,
    simular_extrato,
)


def _dt(dia: int) -> datetime:
    return datetime(2026, 8, dia, 20, 0, tzinfo=timezone.utc)


def _entrada(pick_id, dia, odd, resultado) -> EntradaLedger:
    return EntradaLedger(
        pick_id=pick_id, fixture_id=f"fix-{pick_id}", kickoff_utc=_dt(dia),
        odd=Decimal(str(odd)), resultado=resultado, fator_retorno=calcular_fator_retorno(resultado, Decimal(str(odd))),
    )


# --- calcular_fator_retorno --------------------------------------------------


def test_fator_retorno_green_e_a_propria_odd():
    assert calcular_fator_retorno("green", Decimal("1.85")) == Decimal("1.85")


def test_fator_retorno_meio_green_e_media_com_1():
    assert calcular_fator_retorno("meio_green", Decimal("1.85")) == Decimal("1.425")


def test_fator_retorno_void_e_1():
    assert calcular_fator_retorno("void", Decimal("1.85")) == Decimal("1")


def test_fator_retorno_meio_red_e_0_5():
    assert calcular_fator_retorno("meio_red", Decimal("1.85")) == Decimal("0.5")


def test_fator_retorno_red_e_0():
    assert calcular_fator_retorno("red", Decimal("1.85")) == Decimal("0")


# --- calcular_taxa_acerto (compartilhado entre Fase 6c e 6d) ------------------


def test_calcular_taxa_acerto_conta_meio_green_como_meio_ponto():
    assert calcular_taxa_acerto(["green", "meio_green", "red", "red"]) == Decimal("1.5") / Decimal("4")


def test_calcular_taxa_acerto_exclui_void_do_denominador():
    assert calcular_taxa_acerto(["green", "void"]) == Decimal("1")


def test_calcular_taxa_acerto_none_quando_so_ha_void():
    assert calcular_taxa_acerto(["void", "void"]) is None


def test_calcular_taxa_acerto_none_lista_vazia():
    assert calcular_taxa_acerto([]) is None


# --- ordenar_deterministico ---------------------------------------------------


def test_ordenar_deterministico_por_kickoff():
    e1 = _entrada("p2", 10, 2.0, "green")
    e2 = _entrada("p1", 9, 2.0, "green")
    assert ordenar_deterministico([e1, e2]) == [e2, e1]


def test_ordenar_deterministico_desempata_por_pick_id():
    e1 = _entrada("p2", 10, 2.0, "green")
    e2 = _entrada("p1", 10, 2.0, "green")
    assert ordenar_deterministico([e1, e2]) == [e2, e1]


# --- simular_extrato -----------------------------------------------------------


def test_simular_extrato_modo_fixo_stake_sempre_sobre_banca_inicial():
    entradas = [_entrada("p1", 9, 2.0, "green"), _entrada("p2", 10, 1.5, "red")]

    apostas = simular_extrato(entradas, banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="fixo")

    assert [a.stake_valor for a in apostas] == [Decimal("20.00"), Decimal("20.00")]
    assert apostas[0].banca_antes == Decimal("1000")
    assert apostas[0].banca_depois == Decimal("1020.00")
    assert apostas[1].banca_antes == Decimal("1020.00")
    assert apostas[1].banca_depois == Decimal("1000.00")
    assert [a.sequencia for a in apostas] == [1, 2]


def test_simular_extrato_modo_proporcional_stake_sobre_banca_atual():
    entradas = [_entrada("p1", 9, 2.0, "green"), _entrada("p2", 10, 1.5, "red")]

    apostas = simular_extrato(
        entradas, banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="proporcional"
    )

    assert apostas[0].stake_valor == Decimal("20.00")
    assert apostas[0].banca_depois == Decimal("1020.00")
    assert apostas[1].stake_valor == Decimal("20.40")  # 2% de 1020, nao de 1000
    assert apostas[1].banca_depois == Decimal("999.60")


def test_simular_extrato_void_devolve_stake_sem_lucro_nem_perda():
    entradas = [_entrada("p1", 9, 2.0, "void")]

    apostas = simular_extrato(entradas, banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="fixo")

    assert apostas[0].retorno == Decimal("20.00")
    assert apostas[0].banca_depois == Decimal("1000.00")


def test_simular_extrato_meio_green_meio_red():
    entradas = [_entrada("p1", 9, 2.0, "meio_green"), _entrada("p2", 10, 2.0, "meio_red")]

    apostas = simular_extrato(entradas, banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="fixo")

    # meio_green: fator (2+1)/2=1.5 -> retorno 20*1.5=30, banca 1000-20+30=1010
    assert apostas[0].banca_depois == Decimal("1010.00")
    # meio_red: fator 0.5 -> retorno 20*0.5=10, banca 1010-20+10=1000
    assert apostas[1].banca_depois == Decimal("1000.00")


def test_simular_extrato_lista_vazia():
    assert simular_extrato([], banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="fixo") == []


def test_simular_extrato_ordena_antes_de_replay_mesmo_entrada_fora_de_ordem():
    fora_de_ordem = [_entrada("p2", 10, 1.5, "red"), _entrada("p1", 9, 2.0, "green")]

    apostas = simular_extrato(
        fora_de_ordem, banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="fixo"
    )

    assert [a.pick_id for a in apostas] == ["p1", "p2"]


def test_simular_extrato_e_deterministico_reprocessar_da_o_mesmo_resultado():
    entradas = [
        _entrada("p1", 9, 2.0, "green"), _entrada("p2", 10, 1.5, "red"),
        _entrada("p3", 11, 1.8, "meio_green"), _entrada("p4", 12, 1.4, "void"),
    ]
    kwargs = dict(banca_inicial=Decimal("1000"), stake_pct=Decimal("0.02"), modo_stake="proporcional")

    assert simular_extrato(entradas, **kwargs) == simular_extrato(entradas, **kwargs)


# --- filtrar_por_periodos_assinatura -------------------------------------------


def test_filtrar_por_periodos_mantem_dentro_do_periodo():
    entradas = [_entrada("p1", 15, 2.0, "green")]
    assert filtrar_por_periodos_assinatura(entradas, [(date(2026, 8, 1), date(2026, 8, 31))]) == entradas


def test_filtrar_por_periodos_remove_fora_do_periodo():
    entradas = [_entrada("p1", 15, 2.0, "green")]
    assert filtrar_por_periodos_assinatura(entradas, [(date(2026, 1, 1), date(2026, 1, 31))]) == []


def test_filtrar_por_periodos_gap_de_inadimplencia_nao_gera_entrada_mas_nao_quebra_a_uniao():
    # Assinou em 01-10/ago, ficou inadimplente 11-19/ago, voltou 20-31/ago.
    entradas = [
        _entrada("p1", 5, 2.0, "green"),   # dentro do 1o periodo
        _entrada("p2", 15, 2.0, "green"),  # no gap - nunca deve aparecer
        _entrada("p3", 25, 2.0, "green"),  # dentro do 2o periodo
    ]
    periodos = [(date(2026, 8, 1), date(2026, 8, 10)), (date(2026, 8, 20), date(2026, 8, 31))]

    resultado = filtrar_por_periodos_assinatura(entradas, periodos)

    assert [e.pick_id for e in resultado] == ["p1", "p3"]


def test_filtrar_por_periodos_sem_nenhum_periodo():
    entradas = [_entrada("p1", 15, 2.0, "green")]
    assert filtrar_por_periodos_assinatura(entradas, []) == []


def test_filtrar_por_periodos_converte_kickoff_pro_fuso_de_sao_paulo_antes_de_comparar():
    # Achado do code-reviewer: kickoff as 22h BRT (comum em futebol
    # brasileiro) e' 01h UTC do dia SEGUINTE - comparar .date() direto em
    # UTC excluiria essa entrada de uma assinatura que terminou naquele
    # dia em horario local, mesmo que o jogo tenha comecado dentro do
    # periodo pago.
    kickoff_22h_brt_dia_10 = datetime(2026, 8, 11, 1, 0, tzinfo=timezone.utc)  # 22h BRT do dia 10
    entrada = EntradaLedger(
        pick_id="p1", fixture_id="fix-p1", kickoff_utc=kickoff_22h_brt_dia_10,
        odd=Decimal("2.0"), resultado="green", fator_retorno=Decimal("2.0"),
    )
    periodos = [(date(2026, 8, 1), date(2026, 8, 10))]

    assert filtrar_por_periodos_assinatura([entrada], periodos) == [entrada]
