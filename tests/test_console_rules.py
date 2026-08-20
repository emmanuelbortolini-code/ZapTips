from datetime import date

from app.console.queries import HistoricoColeta
from app.console.rules import FONTES_COLETA, ProjecaoQuota, dias_fora_por_fonte, projetar_quota


def test_projetar_quota_sem_limite():
    quota = projetar_quota(chamadas=30, limite=None, hoje=date(2026, 8, 10))

    assert quota == ProjecaoQuota(chamadas=30, limite=None, restante=None, projecao_fim_mes=quota.projecao_fim_mes)
    assert quota.restante is None


def test_projetar_quota_calcula_restante_e_projecao():
    # 10 dias passados de agosto (31 dias), 20 chamadas -> media 2/dia -> projecao 62
    quota = projetar_quota(chamadas=20, limite=250, hoje=date(2026, 8, 10))

    assert quota.restante == 230
    assert quota.projecao_fim_mes == 62


def test_projetar_quota_dia_1_do_mes_nao_divide_por_zero():
    quota = projetar_quota(chamadas=0, limite=250, hoje=date(2026, 8, 1))

    assert quota.projecao_fim_mes == 0
    assert quota.restante == 250


def test_dias_fora_por_fonte_zero_quando_hoje_esta_ok():
    historico = [HistoricoColeta(data=date(2026, 8, 11), subetapas={"eagle_predict": {"status": "ok"}})]

    resultado = dias_fora_por_fonte(historico, FONTES_COLETA)

    assert resultado["eagle_predict"] == 0


def test_dias_fora_por_fonte_conta_sequencia_ate_achar_ok():
    historico = [
        HistoricoColeta(data=date(2026, 8, 11), subetapas={"eagle_predict": {"status": "degradado"}}),
        HistoricoColeta(data=date(2026, 8, 10), subetapas={"eagle_predict": {"status": "degradado"}}),
        HistoricoColeta(data=date(2026, 8, 9), subetapas={"eagle_predict": {"status": "ok"}}),
    ]

    resultado = dias_fora_por_fonte(historico, FONTES_COLETA)

    assert resultado["eagle_predict"] == 2


def test_dias_fora_por_fonte_ignora_dias_sem_dado_da_fonte():
    historico = [
        HistoricoColeta(data=date(2026, 8, 11), subetapas={"eagle_predict": {"status": "degradado"}}),
        HistoricoColeta(data=date(2026, 8, 10), subetapas={}),  # etapa coleta rodou mas essa fonte nao apareceu
        HistoricoColeta(data=date(2026, 8, 9), subetapas={"eagle_predict": {"status": "ok"}}),
    ]

    resultado = dias_fora_por_fonte(historico, FONTES_COLETA)

    assert resultado["eagle_predict"] == 1


def test_dias_fora_por_fonte_sem_nenhum_ok_no_historico_conta_tudo():
    historico = [HistoricoColeta(data=date(2026, 8, d), subetapas={"sda": {"status": "degradado"}}) for d in (11, 10, 9)]

    resultado = dias_fora_por_fonte(historico, FONTES_COLETA)

    assert resultado["sda"] == 3


def test_dias_fora_por_fonte_cobre_todas_as_fontes_pedidas():
    resultado = dias_fora_por_fonte([], FONTES_COLETA)
    assert set(resultado.keys()) == set(FONTES_COLETA)
    assert all(v == 0 for v in resultado.values())
