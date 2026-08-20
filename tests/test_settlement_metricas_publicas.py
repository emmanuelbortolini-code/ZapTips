from datetime import datetime, timezone
from decimal import Decimal

from app.settlement.banca import Aposta
from app.settlement.metricas import ApostaComData
from app.settlement.metricas_publicas import (
    NOME_7_DIAS,
    NOME_30_DIAS,
    NOME_DESDE_O_INICIO,
    limites_dos_periodos,
    montar_curva_banca,
    montar_periodos_publicos,
)


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


def test_montar_curva_banca_comeca_com_a_banca_inicial_sem_kickoff():
    curva = montar_curva_banca(Decimal("1000"), [])
    assert curva == [(None, Decimal("1000"))]


def test_montar_curva_banca_inclui_um_ponto_por_aposta():
    apostas = [_aposta("p1", 10, 2.0, "green", 20, 40, 1020), _aposta("p2", 11, 2.0, "red", 20, 0, 1000)]
    curva = montar_curva_banca(Decimal("1000"), apostas)
    assert curva == [(None, Decimal("1000")), (_dt(10), Decimal("1020")), (_dt(11), Decimal("1000"))]


def test_limites_dos_periodos_tem_os_tres_nomes_da_spec():
    limites = limites_dos_periodos(_dt(20))
    assert set(limites) == {NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO}
    assert limites[NOME_DESDE_O_INICIO] is None
    assert limites[NOME_30_DIAS] < limites[NOME_7_DIAS] < _dt(20)


def test_montar_periodos_publicos_devolve_um_periodo_por_nome():
    apostas = [_aposta("p1", 10, 2.0, "green", 20, 40, 1020)]
    periodos = montar_periodos_publicos(
        apostas, banca_inicial=Decimal("1000"), agora=_dt(20),
        nao_liquidados_por_periodo={NOME_7_DIAS: 0, NOME_30_DIAS: 1, NOME_DESDE_O_INICIO: 2},
    )
    nomes = [p.nome for p in periodos]
    assert nomes == [NOME_7_DIAS, NOME_30_DIAS, NOME_DESDE_O_INICIO]


def test_montar_periodos_publicos_repassa_nao_liquidados_por_periodo():
    periodos = montar_periodos_publicos(
        [], banca_inicial=Decimal("1000"), agora=_dt(20),
        nao_liquidados_por_periodo={NOME_7_DIAS: 3, NOME_30_DIAS: 5, NOME_DESDE_O_INICIO: 9},
    )
    por_nome = {p.nome: p.metricas.nao_liquidados_no_periodo for p in periodos}
    assert por_nome == {NOME_7_DIAS: 3, NOME_30_DIAS: 5, NOME_DESDE_O_INICIO: 9}


def test_montar_periodos_publicos_desde_o_inicio_inclui_todas_as_apostas():
    apostas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020), _aposta("p2", 19, 2.0, "green", 20, 40, 1040)]
    periodos = montar_periodos_publicos(
        apostas, banca_inicial=Decimal("1000"), agora=_dt(20),
        nao_liquidados_por_periodo={NOME_7_DIAS: 0, NOME_30_DIAS: 0, NOME_DESDE_O_INICIO: 0},
    )
    desde_o_inicio = next(p for p in periodos if p.nome == NOME_DESDE_O_INICIO)
    assert desde_o_inicio.metricas.apostas_no_periodo == 2


def test_montar_periodos_publicos_7_dias_filtra_apostas_antigas():
    apostas = [_aposta("p1", 1, 2.0, "green", 20, 40, 1020), _aposta("p2", 19, 2.0, "green", 20, 40, 1040)]
    periodos = montar_periodos_publicos(
        apostas, banca_inicial=Decimal("1000"), agora=_dt(20),
        nao_liquidados_por_periodo={NOME_7_DIAS: 0, NOME_30_DIAS: 0, NOME_DESDE_O_INICIO: 0},
    )
    sete_dias = next(p for p in periodos if p.nome == NOME_7_DIAS)
    assert sete_dias.metricas.apostas_no_periodo == 1
