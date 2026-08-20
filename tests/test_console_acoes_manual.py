from decimal import Decimal

import pytest

from app.console.acoes import FixturaInvalida, MercadoInvalido, PisoAbaixoDoAbsoluto, criar_palpite_manual
from tests._fakes import FakeCursor


def _args(**overrides):
    base = dict(
        slate_id="slate-1", fixture_id="fix-1", mercado="1x2", selecao="Home win",
        odd_referencia=Decimal("1.90"), operador_nome="pm", odd_minima_absoluta=1.40, margem_pct=0.04,
    )
    base.update(overrides)
    return base


def test_criar_palpite_manual_recusa_mercado_invalido():
    cur = FakeCursor()

    with pytest.raises(MercadoInvalido):
        criar_palpite_manual(cur, **_args(mercado="chute_de_meio_de_campo"))

    assert cur.queries == []


def test_criar_palpite_manual_recusa_odd_abaixo_do_absoluto():
    cur = FakeCursor()

    with pytest.raises(PisoAbaixoDoAbsoluto):
        criar_palpite_manual(cur, **_args(odd_referencia=Decimal("1.20")))

    assert cur.queries == []


def test_criar_palpite_manual_recusa_fixture_fora_de_escopo():
    cur = FakeCursor(fetchone_results=[None])  # busca da fixture nao acha nada elegivel

    with pytest.raises(FixturaInvalida):
        criar_palpite_manual(cur, **_args())

    assert not any("insert into raw_picks" in q[0] for q in cur.queries)


def test_criar_palpite_manual_grava_as_tres_tabelas_na_ordem():
    cur = FakeCursor(
        fetchone_results=[
            ("fix-1", "Goias", "Londrina"),  # busca da fixture elegivel
            ("source-console-manual",),  # id da fonte console_manual
            ("raw-pick-1",),  # insert raw_picks returning id
            ("pick-1",),  # insert picks returning id
            (0,),  # coalesce(max(ordem), 0)
        ]
    )

    pick_id = criar_palpite_manual(cur, **_args())

    assert pick_id == "pick-1"
    sqls = [q[0] for q in cur.queries]
    idx_raw_picks = next(i for i, s in enumerate(sqls) if "insert into raw_picks" in s)
    idx_picks = next(i for i, s in enumerate(sqls) if "insert into picks" in s)
    idx_slate_picks = next(i for i, s in enumerate(sqls) if "insert into slate_picks" in s)

    assert any("curadoria_iniciada_em" in s for s in sqls)
    assert idx_raw_picks < idx_picks < idx_slate_picks


def test_criar_palpite_manual_marca_raw_pick_como_extraido_na_criacao():
    # Achado real: sem extraido_em preenchido aqui, este raw_pick
    # apareceria pra sempre como pendente de extracao (automatica ou
    # assistida por agente) - e reprocessa-lo criaria um segundo pick
    # duplicado em cima do que este proprio fluxo ja insere abaixo.
    cur = FakeCursor(
        fetchone_results=[
            ("fix-1", "Goias", "Londrina"),
            ("source-console-manual",),
            ("raw-pick-1",),
            ("pick-1",),
            (0,),
        ]
    )

    criar_palpite_manual(cur, **_args())

    insert_raw_picks_sql, _ = next(q for q in cur.queries if "insert into raw_picks" in q[0])
    assert "extraido_em" in insert_raw_picks_sql


def test_criar_palpite_manual_usa_time_casa_fora_da_fixture_resolvida():
    cur = FakeCursor(
        fetchone_results=[
            ("fix-1", "Goias", "Londrina"),
            ("source-console-manual",),
            ("raw-pick-1",),
            ("pick-1",),
            (2,),
        ]
    )

    criar_palpite_manual(cur, **_args())

    insert_picks_sql, insert_picks_params = next(q for q in cur.queries if "insert into picks" in q[0])
    assert "Goias" in insert_picks_params
    assert "Londrina" in insert_picks_params


def test_criar_palpite_manual_ordem_sequencial_apos_ultimo_item():
    cur = FakeCursor(
        fetchone_results=[
            ("fix-1", "Goias", "Londrina"),
            ("source-console-manual",),
            ("raw-pick-1",),
            ("pick-1",),
            (3,),  # ja existem 3 itens no slate
        ]
    )

    criar_palpite_manual(cur, **_args())

    insert_slate_picks_sql, insert_slate_picks_params = next(q for q in cur.queries if "insert into slate_picks" in q[0])
    assert 4 in insert_slate_picks_params
