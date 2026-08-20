from datetime import datetime, timezone
from decimal import Decimal

from app.settlement.banca import Aposta
from app.settlement.metricas import ApostaComData, calcular_metricas


def _dt(dia: int) -> datetime:
    return datetime(2026, 8, dia, 20, 0, tzinfo=timezone.utc)


def _aposta(pick_id, dia, odd, resultado, stake, retorno, banca_depois, seq=1) -> ApostaComData:
    aposta = Aposta(
        pick_id=pick_id, fixture_id=f"fix-{pick_id}", message_id=None, odd=Decimal(str(odd)),
        stake_valor=Decimal(str(stake)), stake_pct=Decimal("0.02"), resultado=resultado,
        retorno=Decimal(str(retorno)), banca_antes=Decimal("0"), banca_depois=Decimal(str(banca_depois)),
        sequencia=seq,
    )
    return ApostaComData(aposta=aposta, kickoff_utc=_dt(dia))


# --- banca atual / variacao -------------------------------------------------


def test_banca_atual_sem_apostas_e_banca_inicial():
    m = calcular_metricas([], banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.banca_atual == Decimal("1000")
    assert m.variacao_absoluta == Decimal("0")


def test_banca_atual_e_a_ultima_banca_depois_independente_do_periodo():
    todas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020), _aposta("p2", 20, 2.0, "green", 20, 40, 1040)]
    # periodo de 7 dias (desde dia 25) nao inclui nenhuma aposta, mas
    # banca_atual continua sendo a mais recente de TODAS as apostas.
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=_dt(25), nao_liquidados_no_periodo=0)
    assert m.banca_atual == Decimal("1040")
    assert m.apostas_no_periodo == 0


def test_variacao_desde_o_inicio_usa_banca_inicial_como_ponto_de_partida():
    todas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.variacao_absoluta == Decimal("20")
    assert m.variacao_percentual == Decimal("20") / Decimal("1000")


def test_variacao_de_janela_usa_banca_depois_da_ultima_aposta_antes_da_janela():
    todas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020), _aposta("p2", 10, 2.0, "red", 20, 0, 1000)]
    # janela comeca no dia 5 - so p2 entra, ponto de partida e' banca
    # depois de p1 (1020), nao banca_inicial.
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=_dt(5), nao_liquidados_no_periodo=0)
    assert m.apostas_no_periodo == 1
    assert m.variacao_absoluta == Decimal("1000") - Decimal("1020")


def test_variacao_de_janela_sem_nenhuma_aposta_antes_usa_banca_inicial():
    # Primeira aposta do usuario cai DENTRO da janela pedida - nao ha
    # nenhuma aposta anterior pra herdar banca_depois, entao o ponto de
    # partida e' a banca_inicial mesmo, igual ao caso "desde o inicio".
    todas = [_aposta("p1", 10, 2.0, "green", 20, 40, 1020)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=_dt(5), nao_liquidados_no_periodo=0)
    assert m.variacao_absoluta == Decimal("20")


def test_variacao_percentual_none_quando_banca_inicio_periodo_e_zero():
    m = calcular_metricas([], banca_inicial=Decimal("0"), desde=None, nao_liquidados_no_periodo=0)
    assert m.variacao_percentual is None


# --- total apostado / lucro / roi -----------------------------------------------


def test_total_apostado_lucro_roi():
    todas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020), _aposta("p2", 2, 2.0, "red", 20, 0, 1000)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.total_apostado == Decimal("40")
    assert m.lucro == Decimal("0")
    assert m.roi == Decimal("0")


def test_roi_none_sem_apostas_no_periodo():
    m = calcular_metricas([], banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.roi is None
    assert m.total_apostado == Decimal("0")


# --- taxa de acerto -------------------------------------------------------------


def test_taxa_acerto_conta_meio_green_como_meio_ponto():
    todas = [
        _aposta("p1", 1, 2.0, "green", 20, 40, 1020),
        _aposta("p2", 2, 2.0, "meio_green", 20, 30, 1030),
        _aposta("p3", 3, 2.0, "red", 20, 0, 1010),
        _aposta("p4", 4, 2.0, "red", 20, 0, 990),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    # (1 + 0.5 + 0 + 0) / 4 = 0.375
    assert m.taxa_acerto == Decimal("1.5") / Decimal("4")


def test_taxa_acerto_exclui_void_do_denominador():
    todas = [
        _aposta("p1", 1, 2.0, "green", 20, 40, 1020),
        _aposta("p2", 2, 2.0, "void", 20, 20, 1020),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.taxa_acerto == Decimal("1")  # 1/1, void fora


def test_taxa_acerto_none_quando_so_ha_void():
    todas = [_aposta("p1", 1, 2.0, "void", 20, 20, 1000)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.taxa_acerto is None


# --- odd media -------------------------------------------------------------------


def test_odd_media():
    todas = [_aposta("p1", 1, 1.5, "green", 20, 30, 1010), _aposta("p2", 2, 2.5, "red", 20, 0, 990)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.odd_media == Decimal("2.0")


def test_odd_media_none_sem_apostas():
    m = calcular_metricas([], banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.odd_media is None


# --- drawdown maximo + recuperacao ------------------------------------------------


def test_drawdown_maximo_e_tempo_de_recuperacao():
    todas = [
        _aposta("p1", 1, 2.0, "green", 100, 200, 1100),  # pico
        _aposta("p2", 2, 2.0, "red", 100, 0, 900),
        _aposta("p3", 3, 2.0, "red", 100, 0, 800),  # vale do maior drawdown (300 do pico 1100)
        _aposta("p4", 4, 2.0, "green", 100, 200, 1050),  # ainda abaixo do pico
        _aposta("p5", 5, 2.0, "green", 100, 200, 1150),  # recupera (supera 1100)
        _aposta("p6", 6, 2.0, "green", 100, 200, 1200),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.drawdown_maximo == Decimal("300")
    assert m.dias_para_recuperar == 2  # do dia 3 (vale) ao dia 5 (recuperacao)


def test_drawdown_sem_recuperacao_ainda():
    todas = [
        _aposta("p1", 1, 2.0, "green", 100, 200, 1100),
        _aposta("p2", 2, 2.0, "red", 100, 0, 900),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.drawdown_maximo == Decimal("200")
    assert m.dias_para_recuperar is None


def test_sem_drawdown_banca_so_sobe():
    todas = [_aposta("p1", 1, 2.0, "green", 100, 200, 1100), _aposta("p2", 2, 2.0, "green", 100, 200, 1200)]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.drawdown_maximo == Decimal("0")
    assert m.dias_para_recuperar is None


# --- sequencia atual ---------------------------------------------------------------


def test_sequencia_atual_conta_greens_seguidos_no_final():
    todas = [
        _aposta("p1", 1, 2.0, "red", 20, 0, 980),
        _aposta("p2", 2, 2.0, "green", 20, 40, 1000),
        _aposta("p3", 3, 2.0, "green", 20, 40, 1020),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.sequencia_atual == ("green", 2)


def test_sequencia_atual_reseta_com_resultado_diferente():
    todas = [
        _aposta("p1", 1, 2.0, "green", 20, 40, 1020),
        _aposta("p2", 2, 2.0, "green", 20, 40, 1040),
        _aposta("p3", 3, 2.0, "red", 20, 0, 1020),
    ]
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.sequencia_atual == ("red", 1)


def test_sequencia_atual_nao_e_truncada_pelo_periodo():
    # Achado do code-reviewer: sequencia e' estado do "agora" (mesmo
    # raciocinio de banca_atual), nao deve ser subestimada so' porque
    # parte da sequencia comecou antes da janela pedida.
    todas = [_aposta(f"p{i}", i, 2.0, "green", 20, 40, 1000 + i * 20) for i in range(1, 11)]  # 10 greens seguidos
    # janela de "7 dias" comecando no dia 8 - so as 3 ultimas apostas
    # caem dentro da janela, mas a sequencia real e' 10.
    m = calcular_metricas(todas, banca_inicial=Decimal("1000"), desde=_dt(8), nao_liquidados_no_periodo=0)
    assert m.apostas_no_periodo == 3
    assert m.sequencia_atual == ("green", 10)


def test_sequencia_atual_none_sem_apostas():
    m = calcular_metricas([], banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=0)
    assert m.sequencia_atual is None


# --- nao liquidados no periodo -----------------------------------------------------


def test_nao_liquidados_no_periodo_e_sempre_exposto():
    m = calcular_metricas([], banca_inicial=Decimal("1000"), desde=None, nao_liquidados_no_periodo=7)
    assert m.nao_liquidados_no_periodo == 7
