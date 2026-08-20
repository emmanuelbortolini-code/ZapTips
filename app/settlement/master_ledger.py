"""Popula `master_ledger` (Fase 6b) a partir de `pick_results` (Fase 6a)
+ `slate_picks`/`daily_slates` (Fase 4) + `messages` (Fase 5d), aplicando
o criterio de elegibilidade "entra no extrato" (spec, secao 6b):

- pick de slate **aprovado**
- **efetivamente enviado** a pelo menos um assinante (`messages.status =
  'enviada'`)
- **antes do kickoff** (`messages.enviada_em < fixtures.kickoff_utc`)

Palpite removido na curadoria nunca chega em `slate_picks` do slate
aprovado (nao entra, por construcao). Palpite `nao_liquidavel` tambem
fica de fora - so entram resultados reais.

Reconstroi do zero a cada chamada (delete + insert), nunca incremental -
mesma garantia de determinismo que `app.settlement.banca.simular_extrato`
exige ("reprocessar o extrato inteiro tem que dar exatamente o mesmo
resultado, sempre"). Volume esperado (picks publicados por dia) e baixo
o suficiente pra isso ser barato.
"""

from decimal import Decimal

import psycopg

from app.settlement.banca import EntradaLedger, calcular_fator_retorno, ordenar_deterministico

_SQL_CANDIDATOS = """
    select p.id, f.id, f.kickoff_utc, sp.odd_minima, pr.resultado
    from pick_results pr
    join picks p on p.id = pr.pick_id
    join fixtures f on f.id = p.fixture_id
    join slate_picks sp on sp.pick_id = p.id
    join daily_slates ds on ds.id = sp.slate_id
    where pr.resultado != 'nao_liquidavel'
      and ds.status = 'aprovado'
      and sp.odd_minima is not null
      -- so o slate aprovado MAIS RECENTE de cada data conta (achado do
      -- code-reviewer): daily_slates nao tem status "substituido" - um
      -- slate corrigido (migration 0014, correcao vira um slate NOVO,
      -- app.console.acoes::gerar_correcao) deixa o antigo com
      -- status='aprovado' pra sempre. Sem este filtro, um pick removido
      -- ou reprecificado na correcao continuaria contando pelo slate
      -- velho - mesma resolucao de "slate atual" ja usada em
      -- app.daily_slates.buscar_slate_atual, so que restrita a aprovado.
      and ds.criado_em = (
          select max(ds2.criado_em) from daily_slates ds2
          where ds2.data = ds.data and ds2.status = 'aprovado'
      )
      and exists (
          select 1 from messages m
          where m.status = 'enviada'
            and m.enviada_em is not null
            and m.enviada_em < f.kickoff_utc
            and p.id = any(m.pick_ids)
      )
"""


def buscar_candidatos(cur: psycopg.Cursor) -> list[EntradaLedger]:
    cur.execute(_SQL_CANDIDATOS)
    entradas = []
    for pick_id, fixture_id, kickoff_utc, odd_minima, resultado in cur.fetchall():
        odd = Decimal(str(odd_minima))
        entradas.append(
            EntradaLedger(
                pick_id=str(pick_id),
                fixture_id=str(fixture_id),
                kickoff_utc=kickoff_utc,
                odd=odd,
                resultado=resultado,
                fator_retorno=calcular_fator_retorno(resultado, odd),
            )
        )
    return entradas


def reconstruir(cur: psycopg.Cursor) -> int:
    entradas = ordenar_deterministico(buscar_candidatos(cur))

    cur.execute("delete from master_ledger")
    for ordem, entrada in enumerate(entradas, start=1):
        cur.execute(
            """
            insert into master_ledger (pick_id, fixture_id, ordem, odd, resultado, fator_retorno)
            values (%s::uuid, %s::uuid, %s, %s, %s, %s)
            """,
            (entrada.pick_id, entrada.fixture_id, ordem, entrada.odd, entrada.resultado, entrada.fator_retorno),
        )
    return len(entradas)
