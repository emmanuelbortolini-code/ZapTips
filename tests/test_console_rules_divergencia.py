from datetime import datetime, timezone
from decimal import Decimal

from app.console.queries import ItemSlate
from app.console.rules import divergencia_relativa, tem_alerta_divergencia

_KICKOFF = datetime(2026, 8, 11, 21, 0, tzinfo=timezone.utc)


def _item(**overrides) -> ItemSlate:
    base = dict(
        slate_pick_id="sp-1", pick_id="p-1", fixture_id="fix-1", ordem=1, incluido_por="automatico",
        mercado="1x2", selecao="Home win", time_casa="A", time_fora="B", competicao="Serie B",
        kickoff_utc=_KICKOFF, odd_citada=2.00, casa_citada="Bet365",
        odd_referencia=1.85, odd_referencia_origem="oddspapi", odd_minima=1.77,
        tipster="X", fonte_nome="Sites de Apostas",
    )
    base.update(overrides)
    return ItemSlate(**base)


def test_divergencia_relativa_valor_exato():
    resultado = divergencia_relativa(2.20, 2.00)
    assert resultado == Decimal("0.10")


def test_divergencia_relativa_none_quando_falta_odd_citada():
    assert divergencia_relativa(None, 2.00) is None


def test_divergencia_relativa_none_quando_falta_odd_referencia():
    assert divergencia_relativa(2.00, None) is None


def test_tem_alerta_divergencia_acima_do_limite():
    item = _item(odd_citada=2.20, odd_referencia=2.00)
    assert tem_alerta_divergencia(item, limite_pct=0.10) is False  # exatamente no limite, nao acima

    item_maior = _item(odd_citada=2.30, odd_referencia=2.00)
    assert tem_alerta_divergencia(item_maior, limite_pct=0.10) is True


def test_tem_alerta_divergencia_false_quando_falta_odd_citada():
    item = _item(odd_citada=None)
    assert tem_alerta_divergencia(item, limite_pct=0.10) is False
