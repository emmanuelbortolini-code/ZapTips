from datetime import date, datetime, timezone

from app.slate import PickParaSlate, detectar_e_resolver_conflitos, instante_de_corte, montar_slate


def _pick(
    pick_id, fixture_id="fix-1", mercado="1x2", selecao="casa", time_casa=None, time_fora=None, odd=1.8, confianca=0.9
) -> PickParaSlate:
    return PickParaSlate(
        pick_id=pick_id, fixture_id=fixture_id, mercado=mercado, selecao=selecao,
        time_casa=time_casa, time_fora=time_fora,
        odd_referencia=odd, odd_referencia_em=None, odd_referencia_origem="fonte",
        odd_minima=1.5, confianca_tipster=confianca,
    )


def test_sem_conflito_quando_mesma_selecao_no_grupo():
    picks = [_pick("p1", selecao="casa"), _pick("p2", selecao="casa")]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_sem_conflito_entre_fixtures_diferentes():
    picks = [_pick("p1", fixture_id="fix-1", selecao="casa"), _pick("p2", fixture_id="fix-2", selecao="fora")]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_conflito_resolvido_por_maior_consenso():
    # 2 picks dizem "casa", 1 diz "fora" - "casa" vence, "fora" descartado
    picks = [
        _pick("p1", selecao="casa"), _pick("p2", selecao="casa"), _pick("p3", selecao="fora"),
    ]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == [("p3", "descartado")]


def test_conflito_empatado_manda_fixture_inteira_pra_revisao_manual():
    picks = [_pick("p1", selecao="casa"), _pick("p2", selecao="fora")]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert sobreviventes == []
    assert set(decisoes) == {("p1", "revisao_manual"), ("p2", "revisao_manual")}


def test_conflito_so_entre_mesmo_mercado_mesma_fixture():
    # mercados diferentes na mesma fixture nao sao conflito entre si
    picks = [_pick("p1", mercado="1x2", selecao="casa"), _pick("p2", mercado="over_under", selecao="over")]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_sem_conflito_quando_1x2_concorda_com_fraseado_diferente():
    # Achado do code-reviewer: "Home win" (Eagle Predict) e "Vitória do
    # Fluminense" (SDA) sao o MESMO resultado com fraseado diferente -
    # comparar texto bruto tratava isso como desacordo, diluindo o
    # consenso real que de fato existe entre as duas fontes.
    picks = [
        _pick("p1", mercado="1x2", selecao="Home win", time_casa="Fluminense", time_fora="Palmeiras"),
        _pick("p2", mercado="1x2", selecao="Vitória do Fluminense", time_casa="Fluminense", time_fora="Palmeiras"),
    ]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_sem_conflito_quando_over_under_concorda_com_fraseado_diferente():
    # Mesma linha e direcao, fraseado diferente ("Menos de 2.5 gols" vs
    # "Under 2.5") - mesmo achado de normalizacao ja aplicado ao 1x2.
    picks = [
        _pick("p1", mercado="over_under", selecao="Menos de 2.5 gols"),
        _pick("p2", mercado="over_under", selecao="Under 2.5"),
    ]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_conflito_real_entre_linhas_diferentes_de_over_under():
    # "Menos de 2.5" e "Mais de 3.5" sao linhas DIFERENTES - conflito de
    # verdade, nao um falso desacordo de fraseado.
    picks = [
        _pick("p1", mercado="over_under", selecao="Menos de 2.5 gols"),
        _pick("p2", mercado="over_under", selecao="Mais de 3.5 gols"),
    ]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert sobreviventes == []
    assert set(decisoes) == {("p1", "revisao_manual"), ("p2", "revisao_manual")}


def test_sem_conflito_quando_ambas_marcam_concorda_com_fraseado_diferente():
    picks = [
        _pick("p1", mercado="ambas_marcam", selecao="Ambas marcam: sim"),
        _pick("p2", mercado="ambas_marcam", selecao="BTTS Yes"),
    ]

    sobreviventes, decisoes = detectar_e_resolver_conflitos(picks)

    assert {p.pick_id for p in sobreviventes} == {"p1", "p2"}
    assert decisoes == []


def test_montar_slate_aplica_limite_por_confianca_sem_mudar_status():
    picks = [
        _pick("p1", fixture_id="fix-1", confianca=0.95),
        _pick("p2", fixture_id="fix-2", confianca=0.60),
        _pick("p3", fixture_id="fix-3", confianca=0.80),
    ]

    incluidos, decisoes = montar_slate(picks, slate_max_picks=2)

    assert [p.pick_id for p in incluidos] == ["p1", "p3"]  # os 2 de maior confianca
    assert decisoes == []  # cortado por limite nao gera decisao de status


def test_montar_slate_conflito_e_limite_juntos():
    picks = [
        _pick("p1", fixture_id="fix-1", mercado="1x2", selecao="casa", confianca=0.9),
        _pick("p2", fixture_id="fix-1", mercado="1x2", selecao="casa", confianca=0.8),
        _pick("p3", fixture_id="fix-1", mercado="1x2", selecao="fora", confianca=0.99),  # perde o consenso, fora mesmo com confianca maior
        _pick("p4", fixture_id="fix-2", confianca=0.5),
    ]

    incluidos, decisoes = montar_slate(picks, slate_max_picks=5)

    assert {p.pick_id for p in incluidos} == {"p1", "p2", "p4"}
    assert decisoes == [("p3", "descartado")]


def test_instante_de_corte_soma_inicio_da_sessao_duracao_estimada_e_antecedencia():
    # 09:00 BRT + (30s * 50 assinantes = 25min) + 2h = 11:25 BRT = 14:25 UTC
    corte = instante_de_corte(
        data_slate=date(2026, 8, 11), horario_envio="09:00", intervalo_segundos=30,
        n_assinantes=50, antecedencia_horas=2,
    )

    assert corte == datetime(2026, 8, 11, 14, 25, tzinfo=timezone.utc)


def test_instante_de_corte_com_zero_assinantes_usa_pelo_menos_1_na_duracao():
    # max(1, n_assinantes) - mesmo com 0 assinantes, a duracao estimada
    # nao pode ser zero (evita um corte igual ao inicio da sessao).
    corte = instante_de_corte(
        data_slate=date(2026, 8, 11), horario_envio="09:00", intervalo_segundos=30,
        n_assinantes=0, antecedencia_horas=2,
    )

    assert corte == datetime(2026, 8, 11, 14, 0, 30, tzinfo=timezone.utc)
