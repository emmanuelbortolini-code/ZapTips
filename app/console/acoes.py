"""Escritas de curadoria (Fase 5c) - toda mutacao carimba
daily_slates.curadoria_iniciada_em (migration 0019) antes de tocar
slate_picks, pra scripts/build_slate.py::existe_curadoria_em_andamento
nunca deixar o pipeline apagar/duplicar esse rascunho num re-run.

Decisao de bloqueio (gate liberado? slate ja aprovado?) fica nas rotas +
app/console/rules.py - aqui e so a escrita, sem decidir se ela deveria
acontecer."""

import hashlib
from datetime import date, datetime, timezone
from decimal import Decimal

import psycopg

from app.extraction import MERCADOS_VALIDOS
from app.odds_resolution import calcular_odd_minima
from app.picks_orfaos import upsert_pick_orfao


def marcar_curadoria_iniciada(cur: psycopg.Cursor, slate_id: str) -> None:
    cur.execute(
        "update daily_slates set curadoria_iniciada_em = coalesce(curadoria_iniciada_em, now()) where id = %s::uuid",
        (slate_id,),
    )


def remover_item(cur: psycopg.Cursor, slate_id: str, slate_pick_id: str) -> None:
    marcar_curadoria_iniciada(cur, slate_id)
    cur.execute(
        "delete from slate_picks where id = %s::uuid and slate_id = %s::uuid",
        (slate_pick_id, slate_id),
    )


def reordenar_item(cur: psycopg.Cursor, slate_id: str, slate_pick_id: str, direcao: str) -> None:
    marcar_curadoria_iniciada(cur, slate_id)

    cur.execute("select ordem from slate_picks where id = %s::uuid and slate_id = %s::uuid", (slate_pick_id, slate_id))
    row = cur.fetchone()
    if row is None:
        return
    ordem_atual = row[0]
    ordem_vizinha = ordem_atual + (-1 if direcao == "subir" else 1)

    cur.execute("select id from slate_picks where slate_id = %s::uuid and ordem = %s", (slate_id, ordem_vizinha))
    vizinho = cur.fetchone()
    if vizinho is None:
        return  # ja esta na ponta, nada pra trocar

    cur.execute("update slate_picks set ordem = %s where id = %s::uuid", (ordem_vizinha, slate_pick_id))
    cur.execute("update slate_picks set ordem = %s where id = %s::uuid", (ordem_atual, vizinho[0]))


class PisoAbaixoDoAbsoluto(ValueError):
    pass


def editar_piso(cur: psycopg.Cursor, slate_id: str, slate_pick_id: str, novo_piso: Decimal, odd_minima_absoluta: float) -> None:
    # Achado HIGH do code-reviewer (Fase 5c): sem essa checagem, um piso
    # digitado abaixo do absoluto era gravado sem aviso (bloqueios_de_
    # aprovacao ganhou uma checagem espelhada como defesa em
    # profundidade, mas recusar aqui, na escrita, e mais direto - o
    # operador sabe na hora que o valor nao serve, em vez de descobrir
    # so na tentativa de aprovar).
    if novo_piso < Decimal(str(odd_minima_absoluta)):
        raise PisoAbaixoDoAbsoluto(f"piso {novo_piso} abaixo do minimo absoluto {odd_minima_absoluta:.2f}")

    marcar_curadoria_iniciada(cur, slate_id)
    cur.execute(
        "update slate_picks set odd_minima = %s, odd_minima_origem = 'manual' where id = %s::uuid and slate_id = %s::uuid",
        (novo_piso, slate_pick_id, slate_id),
    )


def editar_odd_referencia(
    cur: psycopg.Cursor, slate_id: str, slate_pick_id: str, nova_odd: Decimal, margem_pct: float, odd_minima_absoluta: float
) -> None:
    # calcular_odd_minima e a mesma formula do motor automatico
    # (app.odds_resolution, Fase 4) - nunca uma segunda formula so pra
    # essa edicao manual. Passa nova_odd (Decimal) direto, sem hop por
    # float (achado LOW do code-reviewer) - Decimal(str(Decimal(...)))
    # e exato, e essa funcao ja e a mesma que teve o bug real de
    # precisao binaria corrigido na Fase 4.
    marcar_curadoria_iniciada(cur, slate_id)
    novo_piso = calcular_odd_minima(nova_odd, margem_pct, odd_minima_absoluta)
    cur.execute(
        """
        update slate_picks
        set odd_referencia = %s, odd_referencia_origem = 'manual', odd_referencia_em = now(),
            odd_minima = %s, odd_minima_origem = 'calculada'
        where id = %s::uuid and slate_id = %s::uuid
        """,
        (nova_odd, novo_piso, slate_pick_id, slate_id),
    )


def aprovar_slate(cur: psycopg.Cursor, slate_id: str, curado_por: str) -> bool:
    # "and status = 'rascunho'" torna uma segunda aprovacao um no-op em
    # vez de reaprovar/re-carimbar curado_em - slate aprovado e imutavel
    # (documento original), aprovar de novo nao deveria mudar nada.
    cur.execute(
        "update daily_slates set status = 'aprovado', curado_em = now(), curado_por = %s where id = %s::uuid and status = 'rascunho' returning id",
        (curado_por, slate_id),
    )
    return cur.fetchone() is not None


def gerar_correcao(cur: psycopg.Cursor, slate_aprovado_id: str) -> str:
    # Slate aprovado e imutavel - correcao gera um slate novo com
    # substitui_slate_id apontando pro aprovado (mesma semantica da
    # migration 0014), copiando os itens como ponto de partida pro
    # operador editar em vez de comecar do zero.
    #
    # A data da correcao vem do PROPRIO slate substituido, nunca de
    # "hoje" (achado do security-reviewer, Fase 5c): usar data_operacional()
    # aqui deixaria corrigir um slate aprovado antigo e o resultado
    # aparecer como se fosse o rascunho de hoje, sombreando o slate real
    # do dia em avaliar_acesso_curadoria/buscar_slate_atual.
    cur.execute("select data from daily_slates where id = %s::uuid", (slate_aprovado_id,))
    row = cur.fetchone()
    if row is None:
        raise ValueError(f"slate nao encontrado: {slate_aprovado_id}")
    data_slate = row[0]

    cur.execute(
        "insert into daily_slates (data, substitui_slate_id) values (%s, %s::uuid) returning id",
        (data_slate, slate_aprovado_id),
    )
    novo_id = str(cur.fetchone()[0])
    cur.execute(
        """
        insert into slate_picks (slate_id, pick_id, ordem, incluido_por, odd_referencia, odd_referencia_em, odd_minima, odd_minima_origem, odd_referencia_origem)
        select %s::uuid, pick_id, ordem, incluido_por, odd_referencia, odd_referencia_em, odd_minima, odd_minima_origem, odd_referencia_origem
        from slate_picks
        where slate_id = %s::uuid
        """,
        (novo_id, slate_aprovado_id),
    )
    return novo_id


def resolver_conflito_usar_selecao(
    cur: psycopg.Cursor, slate_id: str, pick_id: str, fixture_ids: list[str]
) -> bool:
    # Pick perdeu o consenso em app.slate.detectar_e_resolver_conflitos
    # (Fase 4) e ficou revisao_manual, fora de slate_picks, mas conserva
    # a odd_referencia/odd_minima resolvida de quando ainda era
    # vinculado (build_slate.aplicar_decisoes_conflito so muda status).
    #
    # "and status = 'revisao_manual' and fixture_id = any(%s::uuid[])"
    # (achado do security-reviewer, Fase 5c): sem isso, qualquer pick_id
    # - de qualquer status, qualquer fixture, qualquer dia - seria
    # forcado pra 'vinculado' e inserido neste slate. fixture_ids e o
    # conjunto de fixtures que de fato estao no slate (calculado pela
    # rota a partir dos itens carregados), nunca confiar so no slate_id.
    marcar_curadoria_iniciada(cur, slate_id)
    cur.execute(
        "update picks set status = 'vinculado' where id = %s::uuid and status = 'revisao_manual' and fixture_id = any(%s::uuid[]) returning id",
        (pick_id, fixture_ids),
    )
    if cur.fetchone() is None:
        return False

    cur.execute(
        "select odd_referencia, odd_referencia_em, odd_minima, odd_referencia_origem from picks where id = %s::uuid",
        (pick_id,),
    )
    odd_referencia, odd_referencia_em, odd_minima, odd_referencia_origem = cur.fetchone()

    # ordem calculada aqui, nunca recebida do form (achado HIGH do
    # code-reviewer, Fase 5d-E): o template so tinha acesso a `grupo`, a
    # lista de candidatos em conflito para ESTA fixture+mercado (quase
    # sempre 2), nao ao slate inteiro - "loop.length + 1" ali produzia um
    # valor sem relacao com max(ordem) de slate_picks, colidindo com
    # ordem ja existente (sem unique constraint em (slate_id, ordem) pra
    # pegar isso) e quebrando reordenar_item/prioridade de mensagens.
    # Mesmo padrao ja usado em criar_palpite_manual.
    cur.execute("select coalesce(max(ordem), 0) from slate_picks where slate_id = %s::uuid", (slate_id,))
    ordem = cur.fetchone()[0] + 1

    cur.execute(
        """
        insert into slate_picks (slate_id, pick_id, ordem, incluido_por, odd_referencia, odd_referencia_em, odd_minima, odd_referencia_origem)
        values (%s::uuid, %s::uuid, %s, 'manual', %s, %s, %s, %s)
        on conflict (slate_id, pick_id) do nothing
        """,
        (slate_id, pick_id, ordem, odd_referencia, odd_referencia_em, odd_minima, odd_referencia_origem),
    )
    return True


class MercadoInvalido(ValueError):
    pass


class FixturaInvalida(ValueError):
    pass


def criar_palpite_manual(
    cur: psycopg.Cursor,
    *,
    slate_id: str,
    fixture_id: str,
    mercado: str,
    selecao: str,
    odd_referencia: Decimal,
    operador_nome: str,
    odd_minima_absoluta: float,
    margem_pct: float,
) -> str:
    # Palpite manual e a pendencia D3 da Fase 5c. As guardas abaixo
    # existem porque isto e a primeira escrita do console que CRIA linha
    # em raw_picks/picks, nao so em slate_picks - mesma familia de risco
    # do CRITICAL de quarentena da 5c: um formulario aceitando qualquer
    # fixture_id/mercado/odd digitados criaria um pick fantasma que
    # nenhuma outra camada do sistema jamais validou.
    if mercado not in MERCADOS_VALIDOS:
        raise MercadoInvalido(f"mercado invalido: {mercado!r}")
    if odd_referencia < Decimal(str(odd_minima_absoluta)):
        raise PisoAbaixoDoAbsoluto(f"odd {odd_referencia} abaixo do minimo absoluto {odd_minima_absoluta:.2f}")

    marcar_curadoria_iniciada(cur, slate_id)

    # A fixture tem que ser uma das elegiveis HOJE (agendada, kickoff nas
    # proximas 24h) - nunca aceitar fixture_id arbitrario do formulario.
    cur.execute(
        """
        select f.id, tc.nome_canonico, tf.nome_canonico
        from fixtures f
        join teams tc on tc.id = f.home_team_id
        join teams tf on tf.id = f.away_team_id
        where f.id = %s::uuid and f.status = 'agendada'
          and f.kickoff_utc between now() and now() + interval '24 hours'
        """,
        (fixture_id,),
    )
    row = cur.fetchone()
    if row is None:
        raise FixturaInvalida(f"fixture nao elegivel hoje: {fixture_id}")
    _, time_casa, time_fora = row

    cur.execute("select id from sources where nome = 'console_manual'", ())
    source_id = cur.fetchone()[0]

    agora = datetime.now(timezone.utc)
    hash_conteudo = hashlib.sha256(
        f"console_manual|{slate_id}|{fixture_id}|{mercado}|{selecao}|{agora.isoformat()}".encode()
    ).hexdigest()
    texto_bruto = f"[palpite manual] {time_casa} x {time_fora} - {mercado}: {selecao} @ {odd_referencia}"

    # extraido_em preenchido na propria criacao: este raw_pick ja nasce
    # totalmente estruturado (o operador digitou mercado/selecao/odd no
    # formulario, o insert em picks logo abaixo grava isso direto) - sem
    # isso, `buscar_raw_picks_pendentes` (scripts/extract_picks.py, ou a
    # extracao assistida por agente que a substitui) o trataria como
    # pendente pra sempre, e reprocessa-lo criaria um pick duplicado pra
    # cima do que ja foi inserido abaixo, apontando pro mesmo raw_pick_id.
    cur.execute(
        "insert into raw_picks (source_id, texto_bruto, autor, publicado_em, hash_conteudo, extraido_em) "
        "values (%s::uuid, %s, %s, now(), %s, now()) returning id",
        (source_id, texto_bruto, operador_nome, hash_conteudo),
    )
    raw_pick_id = cur.fetchone()[0]

    odd_minima = calcular_odd_minima(float(odd_referencia), margem_pct, odd_minima_absoluta)
    cur.execute(
        """
        insert into picks (
            raw_pick_id, fixture_id, mercado, selecao, time_casa, time_fora,
            odd_referencia, odd_referencia_origem, odd_referencia_em, odd_minima, tipster, status
        )
        values (%s::uuid, %s::uuid, %s, %s, %s, %s, %s, 'manual', now(), %s, %s, 'vinculado')
        returning id
        """,
        (raw_pick_id, fixture_id, mercado, selecao, time_casa, time_fora, odd_referencia, odd_minima, operador_nome),
    )
    pick_id = str(cur.fetchone()[0])

    cur.execute("select coalesce(max(ordem), 0) from slate_picks where slate_id = %s::uuid", (slate_id,))
    ordem = cur.fetchone()[0] + 1

    cur.execute(
        """
        insert into slate_picks (slate_id, pick_id, ordem, incluido_por, odd_referencia, odd_referencia_em, odd_minima, odd_referencia_origem)
        values (%s::uuid, %s::uuid, %s, 'manual', %s, now(), %s, 'manual')
        """,
        (slate_id, pick_id, ordem, odd_referencia, odd_minima),
    )
    return pick_id


def resolver_conflito_descartar_todas(
    cur: psycopg.Cursor, slate_id: str, pick_ids: list[str], fixture_ids: list[str], motivo: str
) -> None:
    marcar_curadoria_iniciada(cur, slate_id)
    # Mesmo escopo de resolver_conflito_usar_selecao: so afeta pick que
    # de fato esta em conflito (revisao_manual) numa fixture deste slate.
    cur.execute(
        "select id from picks where id = any(%s::uuid[]) and status = 'revisao_manual' and fixture_id = any(%s::uuid[])",
        (pick_ids, fixture_ids),
    )
    ids_validos = [str(row[0]) for row in cur.fetchall()]
    for pick_id in ids_validos:
        cur.execute("update picks set status = 'descartado' where id = %s::uuid", (pick_id,))
        upsert_pick_orfao(cur, pick_id, motivo)


def marcar_enviada(cur: psycopg.Cursor, message_id: str) -> bool:
    # "and status = 'pronta'" e a idempotencia exigida pelo criterio de
    # aceite ("marcar como enviada e idempotente") - segunda chamada nao
    # acha a linha (ja nao esta 'pronta') e devolve False, sem re-gravar
    # enviada_em, mesmo padrao de aprovar_slate (Fase 5c).
    cur.execute(
        "update messages set status = 'enviada', enviada_em = now() where id = %s::uuid and status = 'pronta' returning id",
        (message_id,),
    )
    return cur.fetchone() is not None


def pular(cur: psycopg.Cursor, message_id: str, motivo: str) -> bool:
    if not motivo or not motivo.strip():
        raise ValueError("motivo do pulo nao pode ser vazio")
    cur.execute(
        "update messages set status = 'pulada', motivo_pulo = %s where id = %s::uuid and status = 'pronta' returning id",
        (motivo.strip(), message_id),
    )
    return cur.fetchone() is not None


def iniciar_sessao(cur: psycopg.Cursor, data_sessao: date, slate_id: str, iniciada_por: str) -> str | None:
    # A corrida "dois cliques em Iniciar" e resolvida no banco (indice
    # parcial da migration 0021 + ON CONFLICT DO NOTHING), nunca por um
    # SELECT-antes-de-INSERT em Python - mesmo raciocinio ja usado em
    # upsert_team (Fase 1d) contra a mesma classe de TOCTOU.
    cur.execute(
        """
        insert into envio_sessoes (data, slate_id, iniciada_por)
        values (%s, %s::uuid, %s)
        on conflict (data) where encerrada_em is null do nothing
        returning id
        """,
        (data_sessao, slate_id, iniciada_por),
    )
    row = cur.fetchone()
    return str(row[0]) if row is not None else None


def pausar_sessao(cur: psycopg.Cursor, sessao_id: str) -> bool:
    cur.execute(
        "update envio_sessoes set status = 'pausada', pausada_em = now() where id = %s::uuid and status = 'ativa' returning id",
        (sessao_id,),
    )
    return cur.fetchone() is not None


def retomar_sessao(cur: psycopg.Cursor, sessao_id: str) -> bool:
    cur.execute(
        "update envio_sessoes set status = 'ativa', retomada_em = now() where id = %s::uuid and status = 'pausada' returning id",
        (sessao_id,),
    )
    return cur.fetchone() is not None


def encerrar_sessao(cur: psycopg.Cursor, sessao_id: str, encerrada_por: str, motivo: str) -> bool:
    cur.execute(
        """
        update envio_sessoes
        set status = 'encerrada', encerrada_em = now(), encerrada_por = %s, motivo_encerramento = %s
        where id = %s::uuid and encerrada_em is null
        returning id
        """,
        (encerrada_por, motivo, sessao_id),
    )
    return cur.fetchone() is not None


def regerar_corpos(cur: psycopg.Cursor, novos_corpos: dict[str, str]) -> int:
    # D12 (Fase 5d): botao "regerar mensagem" da spec, pra quando o
    # template mudar - so toca 'pronta' (mensagem ja 'enviada'/'pulada'
    # nunca muda retroativamente). Reaproveitada tambem pela edicao manual
    # de texto em /envio (pedido do PM) - e a mesma operacao de banco
    # (sobrescrever corpo_renderizado de uma mensagem ainda 'pronta'),
    # so muda quem decide o novo texto (o template vs. o operador
    # digitando). Chamada com um dict de 1 item nesse caso.
    atualizadas = 0
    for message_id, corpo in novos_corpos.items():
        cur.execute(
            "update messages set corpo_renderizado = %s where id = %s::uuid and status = 'pronta' returning id",
            (corpo, message_id),
        )
        if cur.fetchone() is not None:
            atualizadas += 1
    return atualizadas
