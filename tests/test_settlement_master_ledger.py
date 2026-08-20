from datetime import datetime, timezone
from decimal import Decimal

from app.settlement.banca import EntradaLedger, calcular_fator_retorno
from app.settlement.master_ledger import buscar_candidatos, reconstruir
from tests._fakes import FakeCursor


def test_buscar_candidatos_mapeia_colunas_e_calcula_fator():
    kickoff = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    cur = FakeCursor(fetchall_results=[[("p1", "fix-1", kickoff, Decimal("1.850"), "green")]])

    candidatos = buscar_candidatos(cur)

    assert candidatos == [
        EntradaLedger(
            pick_id="p1", fixture_id="fix-1", kickoff_utc=kickoff, odd=Decimal("1.850"),
            resultado="green", fator_retorno=calcular_fator_retorno("green", Decimal("1.850")),
        )
    ]
    sql = cur.queries[0][0]
    assert "'aprovado'" in sql and "'enviada'" in sql and "!= 'nao_liquidavel'" in sql
    assert "enviada_em < f.kickoff_utc" in sql
    # Achado do code-reviewer: sem restringir ao slate aprovado MAIS
    # RECENTE de cada data, um pick removido/reprecificado numa correcao
    # (o slate antigo fica 'aprovado' pra sempre, migration 0014)
    # continuaria contando pelo slate velho - mesmo padrao de
    # app.daily_slates.buscar_slate_atual, restrito a status aprovado.
    assert "max(ds2.criado_em)" in sql and "ds2.status = 'aprovado'" in sql


def test_buscar_candidatos_lista_vazia():
    cur = FakeCursor(fetchall_results=[[]])
    assert buscar_candidatos(cur) == []


def test_reconstruir_apaga_tudo_e_reinsere_em_ordem_deterministica():
    kickoff_9 = datetime(2026, 8, 9, 20, 0, tzinfo=timezone.utc)
    kickoff_10 = datetime(2026, 8, 10, 20, 0, tzinfo=timezone.utc)
    # Fora de ordem de proposito - reconstruir precisa ordenar antes de gravar.
    cur = FakeCursor(
        fetchall_results=[
            [
                ("p2", "fix-2", kickoff_10, Decimal("1.500"), "red"),
                ("p1", "fix-1", kickoff_9, Decimal("2.000"), "green"),
            ]
        ]
    )

    total = reconstruir(cur)

    assert total == 2
    assert cur.queries[1][0] == "delete from master_ledger"
    # 2 inserts depois do delete, na ordem p1 (ordem=1) entao p2 (ordem=2)
    insert_p1 = cur.queries[2]
    insert_p2 = cur.queries[3]
    assert insert_p1[1][0] == "p1" and insert_p1[1][2] == 1
    assert insert_p2[1][0] == "p2" and insert_p2[1][2] == 2


def test_reconstruir_sem_candidatos_so_apaga():
    cur = FakeCursor(fetchall_results=[[]])

    total = reconstruir(cur)

    assert total == 0
    assert len(cur.queries) == 2
    assert cur.queries[1][0] == "delete from master_ledger"
