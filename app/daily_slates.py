"""Leituras de daily_slates/slate_picks compartilhadas entre o console
(app/console/queries.py) e o motor de geracao de mensagens
(app/messages_generator.py) - Fase 5d. Extraido daqui em vez de duplicado
nos dois, mesmo criterio ja usado pra extrair upsert_source na revisao
holistica pos-Fase 2 e app.slate.chave_selecao na Fase 5c."""

from datetime import date

import psycopg


def buscar_slate_atual(cur: psycopg.Cursor, data_slate: date) -> tuple[str, str, str | None] | None:
    # "Slate atual" de uma data e o mais recente por criado_em, nao mais
    # uma garantia de unicidade em nivel de schema (migration 0014) -
    # pode haver uma cadeia de correcoes pra mesma data.
    #
    # str(...) explicito nos dois uuid: achado real rodando contra o
    # Postgres de verdade (Fase 5d) - psycopg devolve coluna uuid como
    # `uuid.UUID`, nao `str`, por padrao. `_exigir_pode_escrever`
    # compara `atual[0] != slate_id` contra uma string (path param da
    # URL) - `uuid.UUID.__eq__(str)` nunca e igual, entao TODA escrita
    # era recusada com 409 "slate nao e o rascunho atual de hoje" contra
    # o driver real, mesmo com o slate certo. Os testes com FakeCursor
    # nunca pegaram isso porque sempre usam string nas linhas fake -
    # mesma classe de bug ja vista nas Fases 3 e 5a (uuid.UUID vs str).
    cur.execute(
        "select id, status, substitui_slate_id from daily_slates where data = %s order by criado_em desc limit 1",
        (data_slate,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    slate_id, status, substitui_slate_id = row
    return str(slate_id), status, (str(substitui_slate_id) if substitui_slate_id is not None else None)


def existe_pick_quarentena_no_slate(cur: psycopg.Cursor, slate_id: str) -> bool:
    # Defesa em profundidade (Fase 5c, achado CRITICAL do code-reviewer):
    # checa slate_picks direto, independente de como o item chegou la -
    # nao confia so no filtro das queries de exibicao/conflito. A Fase
    # 5d reusa esta mesma checagem antes de gerar mensagem - mandar
    # texto de fonte quarentenada pra quem paga e o mesmo risco, um
    # nivel acima.
    cur.execute(
        """
        select 1
        from slate_picks sp
        join picks p on p.id = sp.pick_id
        join raw_picks rp on rp.id = p.raw_pick_id
        join sources s on s.id = rp.source_id
        where sp.slate_id = %s::uuid and s.quarentena is true
        limit 1
        """,
        (slate_id,),
    )
    return cur.fetchone() is not None
