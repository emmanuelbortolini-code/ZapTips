from decimal import Decimal

from app.settlement.performance_fonte import (
    MetricasGrupo,
    PickComOdd,
    alertas_nao_liquidados,
    calcular_metricas_grupo,
    sugerir_acoes,
)


def _pick(pick_id, resultado, odd_minima, odd_citada=None, odd_referencia=None) -> PickComOdd:
    return PickComOdd(
        pick_id=pick_id, resultado=resultado, odd_minima=Decimal(str(odd_minima)),
        odd_citada=Decimal(str(odd_citada)) if odd_citada is not None else None,
        odd_referencia=Decimal(str(odd_referencia)) if odd_referencia is not None else None,
    )


# --- calcular_metricas_grupo ----------------------------------------------------


def test_volumes_liquidado_nao_liquidado_sem_odd():
    picks = [_pick("p1", "green", 2.0), _pick("p2", None, 1.5)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=3)

    assert m.volume_liquidado == 1
    assert m.volume_nao_liquidado == 1
    assert m.volume_sem_odd == 3


def test_percentual_nao_liquidados():
    picks = [_pick("p1", "green", 2.0), _pick("p2", None, 1.5), _pick("p3", None, 1.8)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    assert m.percentual_nao_liquidados == Decimal("2") / Decimal("3")


def test_percentual_nao_liquidados_none_sem_nenhuma_tentativa():
    m = calcular_metricas_grupo(("fonte-a",), [], volume_sem_odd=5)
    assert m.percentual_nao_liquidados is None


def test_roi_calculado_com_stake_unitario():
    picks = [_pick("p1", "green", 2.0), _pick("p2", "red", 1.5)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    # fatores: [2.0, 0] -> (2.0 - 2) / 2 = 0
    assert m.roi == Decimal("0")


def test_roi_none_sem_nenhum_liquidado():
    picks = [_pick("p1", None, 2.0)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    assert m.roi is None


def test_taxa_acerto_so_considera_liquidados():
    picks = [_pick("p1", "green", 2.0), _pick("p2", None, 1.5)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    assert m.taxa_acerto == Decimal("1")


def test_odd_media_inclui_liquidados_e_nao_liquidados():
    picks = [_pick("p1", "green", 2.0), _pick("p2", None, 1.5)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=10)
    # sem_odd nunca entra em picks_com_odd (nao tem odd_minima) - so os 2.
    assert m.odd_media == Decimal("1.75")


def test_odd_media_none_grupo_vazio():
    m = calcular_metricas_grupo(("fonte-a",), [], volume_sem_odd=0)
    assert m.odd_media is None


def test_diferenca_media_odd_so_considera_picks_com_ambas():
    picks = [
        _pick("p1", "green", 2.0, odd_citada=2.10, odd_referencia=2.00),
        _pick("p2", "red", 1.5, odd_citada=None, odd_referencia=1.55),  # sem odd_citada, fica de fora
    ]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    assert m.diferenca_media_odd == Decimal("0.10")


def test_diferenca_media_odd_none_sem_nenhum_par_completo():
    picks = [_pick("p1", "green", 2.0)]
    m = calcular_metricas_grupo(("fonte-a",), picks, volume_sem_odd=0)
    assert m.diferenca_media_odd is None


def test_chave_e_preservada():
    m = calcular_metricas_grupo(("fonte-a", "over_under"), [], volume_sem_odd=0)
    assert m.chave == ("fonte-a", "over_under")


# --- sugerir_acoes ---------------------------------------------------------------


def _metricas(chave, roi, volume) -> MetricasGrupo:
    return MetricasGrupo(
        chave=chave, volume_liquidado=volume, volume_nao_liquidado=0, volume_sem_odd=0,
        percentual_nao_liquidados=Decimal("0"), roi=Decimal(str(roi)) if roi is not None else None,
        taxa_acerto=Decimal("0.5"), odd_media=Decimal("2.0"), diferenca_media_odd=None,
    )


def test_sugere_desativacao_fonte_publicada_roi_negativo_volume_suficiente():
    metricas = [_metricas(("fonte-a",), roi=-0.1, volume=40)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-a": False})
    assert len(sugestoes) == 1 and sugestoes[0].tipo == "desativacao"


def test_sugere_promocao_fonte_quarentena_roi_positivo_volume_suficiente():
    metricas = [_metricas(("fonte-b",), roi=0.15, volume=35)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-b": True})
    assert len(sugestoes) == 1 and sugestoes[0].tipo == "promocao"


def test_sem_sugestao_volume_abaixo_do_minimo():
    metricas = [_metricas(("fonte-a",), roi=-0.5, volume=10)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-a": False})
    assert sugestoes == []


def test_sem_sugestao_roi_none():
    metricas = [_metricas(("fonte-a",), roi=None, volume=50)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-a": False})
    assert sugestoes == []


def test_sem_sugestao_fonte_publicada_com_roi_positivo():
    metricas = [_metricas(("fonte-a",), roi=0.1, volume=50)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-a": False})
    assert sugestoes == []


def test_sem_sugestao_fonte_quarentena_com_roi_negativo():
    metricas = [_metricas(("fonte-b",), roi=-0.1, volume=50)]
    sugestoes = sugerir_acoes(metricas, quarentena_por_fonte={"fonte-b": True})
    assert sugestoes == []


# --- alertas_nao_liquidados -------------------------------------------------------


def _metricas_nao_liquidados(chave, volume_liquidado, volume_nao_liquidado) -> MetricasGrupo:
    total = volume_liquidado + volume_nao_liquidado
    percentual = Decimal(volume_nao_liquidado) / total if total else None
    return MetricasGrupo(
        chave=chave, volume_liquidado=volume_liquidado, volume_nao_liquidado=volume_nao_liquidado,
        volume_sem_odd=0, percentual_nao_liquidados=percentual, roi=None, taxa_acerto=None,
        odd_media=None, diferenca_media_odd=None,
    )


def test_alerta_fonte_acima_do_limite_com_volume_suficiente():
    # 4 de 20 = 20%, acima do limite de 15%.
    metricas = [_metricas_nao_liquidados(("fonte-a",), volume_liquidado=16, volume_nao_liquidado=4)]
    alertas = alertas_nao_liquidados(metricas, limite_pct=Decimal("0.15"))
    assert len(alertas) == 1
    assert alertas[0].fonte == "fonte-a"
    assert alertas[0].total_tentado == 20


def test_sem_alerta_fonte_abaixo_do_limite():
    # 2 de 20 = 10%, abaixo do limite de 15%.
    metricas = [_metricas_nao_liquidados(("fonte-a",), volume_liquidado=18, volume_nao_liquidado=2)]
    alertas = alertas_nao_liquidados(metricas, limite_pct=Decimal("0.15"))
    assert alertas == []


def test_sem_alerta_volume_abaixo_do_minimo():
    # 1 de 1 = 100%, mas amostra pequena demais pra confiar no percentual.
    metricas = [_metricas_nao_liquidados(("fonte-a",), volume_liquidado=0, volume_nao_liquidado=1)]
    alertas = alertas_nao_liquidados(metricas, limite_pct=Decimal("0.15"), volume_minimo=10)
    assert alertas == []


def test_sem_alerta_percentual_none():
    metricas = [_metricas_nao_liquidados(("fonte-a",), volume_liquidado=0, volume_nao_liquidado=0)]
    alertas = alertas_nao_liquidados(metricas, limite_pct=Decimal("0.15"))
    assert alertas == []
