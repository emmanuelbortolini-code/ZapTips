from decimal import Decimal

from app.settlement.banca import Aposta
from app.settlement.resumo_semanal import calcular_resumo_semanal


def _aposta(pick_id, odd, resultado, stake, retorno, banca_antes, banca_depois, seq=1) -> Aposta:
    return Aposta(
        pick_id=pick_id, fixture_id=f"fix-{pick_id}", message_id=None, odd=Decimal(str(odd)),
        stake_valor=Decimal(str(stake)), stake_pct=Decimal("0.02"), resultado=resultado,
        retorno=Decimal(str(retorno)), banca_antes=Decimal(str(banca_antes)), banca_depois=Decimal(str(banca_depois)),
        sequencia=seq,
    )


def test_sem_apostas_banca_atual_e_a_do_inicio_da_semana():
    r = calcular_resumo_semanal([], banca_no_inicio_semana=Decimal("1000"), nao_liquidados=0)
    assert r.banca_atual == Decimal("1000")
    assert r.total_palpites == 0
    assert r.roi is None


def test_banca_atual_e_a_da_ultima_aposta_da_semana():
    apostas = [
        _aposta("p1", "1.80", "green", "20", "36", "1000", "1016", seq=1),
        _aposta("p2", "2.00", "red", "20", "0", "1016", "996", seq=2),
    ]
    r = calcular_resumo_semanal(apostas, banca_no_inicio_semana=Decimal("1000"), nao_liquidados=0)
    assert r.banca_atual == Decimal("996")
    assert r.banca_inicial == Decimal("1000")


def test_conta_greens_e_reds_simples_meio_green_conta_como_green_meio_red_como_red():
    apostas = [
        _aposta("p1", "2.0", "green", "20", "40", "1000", "1020"),
        _aposta("p2", "2.0", "meio_green", "20", "30", "1020", "1030"),
        _aposta("p3", "2.0", "red", "20", "0", "1030", "1010"),
        _aposta("p4", "2.0", "meio_red", "20", "10", "1010", "1000"),
        _aposta("p5", "2.0", "void", "20", "20", "1000", "1000"),
    ]
    r = calcular_resumo_semanal(apostas, banca_no_inicio_semana=Decimal("1000"), nao_liquidados=0)
    assert r.total_palpites == 5
    assert r.greens == 2
    assert r.reds == 2


def test_roi_calculado_sobre_stake_e_retorno_da_semana():
    apostas = [
        _aposta("p1", "2.0", "green", "100", "200", "1000", "1100"),
        _aposta("p2", "2.0", "red", "100", "0", "1100", "1000"),
    ]
    r = calcular_resumo_semanal(apostas, banca_no_inicio_semana=Decimal("1000"), nao_liquidados=0)
    # lucro = (200+0) - (100+100) = 0 -> roi = 0
    assert r.roi == Decimal("0")


def test_roi_none_quando_nenhuma_aposta_teve_stake():
    r = calcular_resumo_semanal([], banca_no_inicio_semana=Decimal("1000"), nao_liquidados=0)
    assert r.roi is None


def test_nao_liquidados_passa_direto():
    r = calcular_resumo_semanal([], banca_no_inicio_semana=Decimal("1000"), nao_liquidados=3)
    assert r.nao_liquidados == 3
