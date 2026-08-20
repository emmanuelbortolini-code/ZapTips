"""Extrato por usuario (Fase 6b) - le `master_ledger` (ja com odd/
resultado/fator congelados) e aplica a config e o periodo de assinatura
de UM usuario, gravando o resultado em `bets` (existe desde a Fase 0,
ver docstring de app.settlement.banca pro porque essa tabela nao e'
"duplicar o mestre 200 vezes").

Elegibilidade por usuario: um pick do master_ledger entra no extrato
dele se uma mensagem `enviada` (nao `pronta`/`pulada`/`expirada`) pra
ESSE usuario, antes do kickoff, continha aquele pick - mesmo criterio de
"efetivamente enviado" usado pro extrato mestre (app.settlement.
master_ledger), so trocando "algum assinante" por "este assinante". Isso
evita reaplicar a logica de preferencia (app.messages_generator.
filtrar_por_preferencia) uma segunda vez aqui: a preferencia ja decidiu
quem recebeu o que no momento da geracao da mensagem (Fase 5d) - refazer
esse filtro com a preferencia ATUAL do usuario re-liquidaria o extrato
de forma diferente do que ele de fato recebeu, se a preferencia mudou
depois.
"""

from datetime import date
from decimal import Decimal

import psycopg

from app.settlement.banca import Aposta, EntradaLedger, filtrar_por_periodos_assinatura, simular_extrato

_SQL_ENTRADAS_ELEGIVEIS = """
    select distinct ml.pick_id, ml.fixture_id, f.kickoff_utc, ml.odd, ml.resultado, ml.fator_retorno, m.id
    from master_ledger ml
    join fixtures f on f.id = ml.fixture_id
    join messages m on m.user_id = %s
        and m.status = 'enviada'
        and m.enviada_em is not null
        and m.enviada_em < f.kickoff_utc
        and ml.pick_id = any(m.pick_ids)
"""


def buscar_entradas_elegiveis(cur: psycopg.Cursor, user_id: str) -> list[EntradaLedger]:
    cur.execute(_SQL_ENTRADAS_ELEGIVEIS, (user_id,))
    return [
        EntradaLedger(
            pick_id=str(pick_id), fixture_id=str(fixture_id), kickoff_utc=kickoff_utc,
            odd=Decimal(str(odd)), resultado=resultado, fator_retorno=Decimal(str(fator_retorno)),
            message_id=str(message_id),
        )
        for pick_id, fixture_id, kickoff_utc, odd, resultado, fator_retorno, message_id in cur.fetchall()
    ]


def buscar_periodos_assinatura(cur: psycopg.Cursor, user_id: str) -> list[tuple[date, date]]:
    cur.execute("select inicio, fim from subscriptions where user_id = %s::uuid order by inicio", (user_id,))
    return [(inicio, fim) for inicio, fim in cur.fetchall()]


def buscar_config_banca(cur: psycopg.Cursor, user_id: str, settings) -> tuple[Decimal, Decimal, str]:
    cur.execute(
        "select banca_inicial, stake_pct, modo_stake from user_bankroll_config where user_id = %s::uuid", (user_id,)
    )
    row = cur.fetchone()
    if row is None:
        # Sem linha propria, usa o default do produto (app.config) - a
        # maioria dos usuarios nunca escreveu em user_bankroll_config
        # (nenhum fluxo de cadastro cria essa linha hoje).
        return (
            Decimal(str(settings.banca_inicial_padrao)),
            Decimal(str(settings.stake_pct_padrao)),
            settings.stake_modo_padrao,
        )
    banca_inicial, stake_pct, modo_stake = row
    return Decimal(str(banca_inicial)), Decimal(str(stake_pct)), modo_stake


def gravar_extrato(cur: psycopg.Cursor, user_id: str, apostas: list[Aposta]) -> None:
    cur.execute("delete from bets where user_id = %s::uuid", (user_id,))
    for aposta in apostas:
        cur.execute(
            """
            insert into bets
                (user_id, message_id, pick_id, fixture_id, odd, stake_valor, stake_pct,
                 resultado, retorno, banca_antes, banca_depois, sequencia)
            values (%s::uuid, %s::uuid, %s::uuid, %s::uuid, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                user_id, aposta.message_id, aposta.pick_id, aposta.fixture_id, aposta.odd, aposta.stake_valor,
                aposta.stake_pct, aposta.resultado, aposta.retorno, aposta.banca_antes, aposta.banca_depois,
                aposta.sequencia,
            ),
        )


def reconstruir_extrato_usuario(cur: psycopg.Cursor, user_id: str, settings) -> int:
    entradas = buscar_entradas_elegiveis(cur, user_id)
    periodos = buscar_periodos_assinatura(cur, user_id)
    banca_inicial, stake_pct, modo_stake = buscar_config_banca(cur, user_id, settings)

    elegiveis = filtrar_por_periodos_assinatura(entradas, periodos)
    apostas = simular_extrato(elegiveis, banca_inicial=banca_inicial, stake_pct=stake_pct, modo_stake=modo_stake)

    gravar_extrato(cur, user_id, apostas)
    return len(apostas)
