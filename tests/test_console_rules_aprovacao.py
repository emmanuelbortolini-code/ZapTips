from datetime import datetime, timezone

from app.console.queries import ItemSlate
from app.console.rules import bloqueios_de_aprovacao

_KICKOFF = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)


def _item(**overrides) -> ItemSlate:
    base = dict(
        slate_pick_id="sp-1", pick_id="p-1", fixture_id="fix-1", ordem=1, incluido_por="automatico",
        mercado="1x2", selecao="Home win", time_casa="A", time_fora="B", competicao="Serie B",
        kickoff_utc=_KICKOFF, odd_citada=1.90, casa_citada="Bet365",
        odd_referencia=1.85, odd_referencia_origem="oddspapi", odd_minima=1.77,
        tipster="X", fonte_nome="Sites de Apostas",
    )
    base.update(overrides)
    return ItemSlate(**base)


def test_sem_bloqueio_quando_tudo_ok():
    bloqueios = bloqueios_de_aprovacao([_item()], conflitos={}, odd_minima_absoluta=1.40)
    assert bloqueios == ()


def test_bloqueia_item_sem_odd_referencia():
    bloqueios = bloqueios_de_aprovacao([_item(odd_referencia=None)], conflitos={}, odd_minima_absoluta=1.40)

    assert len(bloqueios) == 1
    assert bloqueios[0].codigo == "sem_odd_referencia"


def test_bloqueia_item_sem_piso():
    bloqueios = bloqueios_de_aprovacao([_item(odd_minima=None)], conflitos={}, odd_minima_absoluta=1.40)

    assert bloqueios[0].codigo == "sem_odd_referencia"


def test_bloqueia_odd_manual_abaixo_do_piso_absoluto():
    # Defesa em profundidade: se o operador digitar uma odd de referencia
    # manual abaixo do piso absoluto, a aprovacao ainda recusa.
    bloqueios = bloqueios_de_aprovacao([_item(odd_referencia=1.20)], conflitos={}, odd_minima_absoluta=1.40)

    assert any(b.codigo == "odd_abaixo_do_piso" for b in bloqueios)


def test_bloqueia_piso_manual_abaixo_do_absoluto_mesmo_com_odd_referencia_ok():
    # Achado HIGH do code-reviewer (Fase 5c): editar_piso deixava gravar
    # odd_minima abaixo do piso absoluto mesmo com odd_referencia valida
    # (bloqueios_de_aprovacao so checava odd_referencia, nunca odd_minima
    # em si) - um slate assim aprovaria com piso publicado errado.
    bloqueios = bloqueios_de_aprovacao([_item(odd_referencia=2.00, odd_minima=1.00)], conflitos={}, odd_minima_absoluta=1.40)

    assert any(b.codigo == "odd_abaixo_do_piso" for b in bloqueios)


def test_bloqueia_conflito_nao_resolvido():
    conflitos = {("fix-1", "1x2"): [("p-9", "Away win", "TipsterY")]}

    bloqueios = bloqueios_de_aprovacao([_item()], conflitos=conflitos, odd_minima_absoluta=1.40)

    assert any(b.codigo == "conflito_nao_resolvido" for b in bloqueios)


def test_varios_bloqueios_simultaneos():
    itens = [_item(odd_referencia=None), _item(slate_pick_id="sp-2", odd_referencia=1.20)]
    conflitos = {("fix-2", "1x2"): [("p-9", "Away win", None)]}

    bloqueios = bloqueios_de_aprovacao(itens, conflitos=conflitos, odd_minima_absoluta=1.40)

    codigos = {b.codigo for b in bloqueios}
    assert codigos == {"sem_odd_referencia", "odd_abaixo_do_piso", "conflito_nao_resolvido"}
