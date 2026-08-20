"""Leitura de dado real pro console (Fase 5c) - funcoes DB-shape, sem
logica de decisao (isso fica em app/console/rules.py, puro). Mesmo split
ja usado em app/pipeline.py + app/pipeline_runs.py: a etapa de decisao
nao sabe de Postgres, a etapa de leitura nao decide nada.

`carregar_estado_run` e deliberadamente separada de
`app.pipeline_runs.carregar_resultados`: essa ultima descarta etapas em
`pendente`/`rodando` de proposito (faz sentido pro resume do
orquestrador, que so quer saber o que ja fechou). O console precisa do
oposto - saber exatamente quais etapas ainda nao rodaram, pra explicar
`avaliar_acesso_curadoria` (Fase 5c) sem inventar um "silencio" que
parece bug."""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

import psycopg

from app.daily_slates import buscar_slate_atual, existe_pick_quarentena_no_slate  # noqa: F401 - reexport (Fase 5d)
from app.picks_orfaos import TIPO_SEM_FIXTURE
from app.pipeline import ETAPAS, StatusEtapa, StatusRun, limites_utc_do_dia
from app.subs import SQL_ASSINANTE_ATIVO


@dataclass(frozen=True)
class EstadoEtapaDetalhado:
    nome: str
    ordem: int
    status: StatusEtapa
    itens_ok: int
    itens_erro: int
    detalhe: dict = field(default_factory=dict)


@dataclass(frozen=True)
class EstadoRun:
    existe: bool
    status: StatusRun | None
    etapa_atual: str | None
    etapas: tuple[EstadoEtapaDetalhado, ...]


def carregar_estado_run(cur: psycopg.Cursor, data_referencia: date) -> EstadoRun:
    cur.execute("select id, status, etapa_atual from pipeline_runs where data_referencia = %s", (data_referencia,))
    row = cur.fetchone()
    if row is None:
        return EstadoRun(existe=False, status=None, etapa_atual=None, etapas=())

    run_id, status, etapa_atual = row
    cur.execute(
        "select etapa, ordem, status, itens_ok, itens_erro, detalhe_json from pipeline_stages where run_id = %s::uuid order by ordem",
        (str(run_id),),
    )
    linhas_por_etapa = {linha[0]: linha for linha in cur.fetchall()}

    etapas = tuple(
        _etapa_detalhada(etapa_spec, linhas_por_etapa.get(etapa_spec.nome)) for etapa_spec in ETAPAS
    )
    return EstadoRun(existe=True, status=status, etapa_atual=etapa_atual, etapas=etapas)


def _etapa_detalhada(etapa_spec, linha) -> EstadoEtapaDetalhado:
    if linha is None:
        return EstadoEtapaDetalhado(nome=etapa_spec.nome, ordem=etapa_spec.ordem, status="pendente", itens_ok=0, itens_erro=0, detalhe={})
    _, ordem, status, itens_ok, itens_erro, detalhe_json = linha
    return EstadoEtapaDetalhado(
        nome=etapa_spec.nome, ordem=ordem, status=status, itens_ok=itens_ok, itens_erro=itens_erro, detalhe=detalhe_json or {}
    )


@dataclass(frozen=True)
class HistoricoColeta:
    data: date
    subetapas: dict = field(default_factory=dict)


def historico_coleta(cur: psycopg.Cursor, dias: int) -> list[HistoricoColeta]:
    cur.execute(
        """
        select r.data_referencia, s.detalhe_json
        from pipeline_runs r
        join pipeline_stages s on s.run_id = r.id and s.etapa = 'coleta'
        order by r.data_referencia desc
        limit %s
        """,
        (dias,),
    )
    return [
        HistoricoColeta(data=data_referencia, subetapas=(detalhe_json or {}).get("subetapas", {}))
        for data_referencia, detalhe_json in cur.fetchall()
    ]


def quota_mes(cur: psycopg.Cursor, mes_referencia: str) -> tuple[int, int | None]:
    cur.execute(
        "select chamadas, limite from api_quota where provedor = 'oddspapi' and mes_referencia = %s",
        (mes_referencia,),
    )
    row = cur.fetchone()
    if row is None:
        return 0, None
    return row[0], row[1]


def orfaos_aguardando_partida(cur: psycopg.Cursor) -> int:
    cur.execute("select count(*) from picks_orfaos where tipo = %s", (TIPO_SEM_FIXTURE,))
    return cur.fetchone()[0]


def encerradas_sem_liquidacao(cur: psycopg.Cursor, horas: int = 12) -> int:
    # join com picks (so fixture com pelo menos um pick vinculado conta -
    # sem isso, o numero incluiria centenas de fixtures que ninguem
    # apostou) + left join pick_results pra achar o que ainda nao foi
    # liquidado (Fase 6 - hoje sempre 0, ver docstring do modulo).
    cur.execute(
        """
        select count(distinct f.id)
        from fixtures f
        join picks p on p.fixture_id = f.id and p.status = 'vinculado'
        left join pick_results pr on pr.pick_id = p.id
        where f.status = 'encerrada'
          and f.kickoff_utc < now() - (%s * interval '1 hour')
          and pr.id is null
        """,
        (horas,),
    )
    return cur.fetchone()[0]


def mensagens_expiradas(cur: psycopg.Cursor) -> int:
    cur.execute("select count(*) from messages where status = 'expirada'")
    return cur.fetchone()[0]


def buscar_status_slate(cur: psycopg.Cursor, slate_id: str) -> str | None:
    cur.execute("select status from daily_slates where id = %s::uuid", (slate_id,))
    row = cur.fetchone()
    return row[0] if row else None


@dataclass(frozen=True)
class FixturaElegivel:
    fixture_id: str
    time_casa: str
    time_fora: str
    liga: str
    kickoff_utc: datetime


def fixturas_elegiveis_do_dia(cur: psycopg.Cursor) -> tuple[FixturaElegivel, ...]:
    # Mesma janela de scripts/build_slate.py::buscar_picks_candidatos
    # (kickoff nas proximas 24h) - alimenta o <select> do formulario de
    # palpite manual (Fase 5d). acoes.criar_palpite_manual reconsulta e
    # revalida isso na escrita, nunca confia so no que o GET ofereceu.
    cur.execute(
        """
        select f.id, tc.nome_canonico, tf.nome_canonico, f.liga, f.kickoff_utc
        from fixtures f
        join teams tc on tc.id = f.home_team_id
        join teams tf on tf.id = f.away_team_id
        where f.status = 'agendada' and f.kickoff_utc between now() and now() + interval '24 hours'
        order by f.kickoff_utc
        """
    )
    return tuple(
        FixturaElegivel(fixture_id=str(row[0]), time_casa=row[1], time_fora=row[2], liga=row[3], kickoff_utc=row[4])
        for row in cur.fetchall()
    )


@dataclass(frozen=True)
class ItemSlate:
    slate_pick_id: str
    pick_id: str
    fixture_id: str
    ordem: int
    incluido_por: str
    mercado: str
    selecao: str
    time_casa: str | None
    time_fora: str | None
    competicao: str | None
    kickoff_utc: datetime
    odd_citada: float | None
    casa_citada: str | None
    odd_referencia: float | None
    odd_referencia_origem: str | None
    odd_minima: float | None
    tipster: str | None
    fonte_nome: str | None


def carregar_itens_slate(cur: psycopg.Cursor, slate_id: str) -> tuple[ItemSlate, ...]:
    # "s.quarentena is not true" - achado central da Fase 5c: nenhum
    # codigo ate aqui filtrava fonte em quarentena, e a spec e taxativa
    # ("nao aparece nesta aba, em hipotese alguma"). As duas fontes reais
    # (Eagle Predict, SDA) seguem em quarentena hoje (decisao do PM, ver
    # CLAUDE.md Fase 5c) - a aba fica corretamente vazia at ela mudar.
    cur.execute(
        """
        select sp.id, sp.pick_id, p.fixture_id, sp.ordem, sp.incluido_por,
               p.mercado, p.selecao, p.time_casa, p.time_fora, p.competicao,
               f.kickoff_utc, p.odd_citada, c.nome,
               sp.odd_referencia, sp.odd_referencia_origem, sp.odd_minima,
               p.tipster, s.nome
        from slate_picks sp
        join picks p on p.id = sp.pick_id
        join fixtures f on f.id = p.fixture_id
        join raw_picks rp on rp.id = p.raw_pick_id
        join sources s on s.id = rp.source_id
        left join casas c on c.id = p.casa_id
        where sp.slate_id = %s::uuid
          and s.quarentena is not true
        order by sp.ordem
        """,
        (slate_id,),
    )
    return tuple(
        ItemSlate(
            slate_pick_id=str(row[0]), pick_id=str(row[1]), fixture_id=str(row[2]), ordem=row[3], incluido_por=row[4],
            mercado=row[5], selecao=row[6], time_casa=row[7], time_fora=row[8], competicao=row[9],
            kickoff_utc=row[10], odd_citada=float(row[11]) if row[11] is not None else None, casa_citada=row[12],
            odd_referencia=float(row[13]) if row[13] is not None else None, odd_referencia_origem=row[14],
            odd_minima=float(row[15]) if row[15] is not None else None,
            tipster=row[16], fonte_nome=row[17],
        )
        for row in cur.fetchall()
    )


def conflitos_por_fixture(cur: psycopg.Cursor, fixture_ids: list[str]) -> dict[tuple[str, str], list[tuple[str, str, str | None]]]:
    # Picks empatados no consenso (app.slate.detectar_e_resolver_conflitos)
    # viram 'revisao_manual' e ficam fora de slate_picks - por isso essa
    # busca e separada, nao um join direto no slate.
    #
    # "s.quarentena is not true" (achado CRITICAL do code-reviewer, Fase
    # 5c, junto com buscar_picks_candidatos): sem isso, o botao "usar
    # esta selecao" oferecia promover um pick de fonte em quarentena de
    # volta pro slate.
    if not fixture_ids:
        return {}
    cur.execute(
        """
        select p.fixture_id, p.mercado, p.id, p.selecao, p.tipster
        from picks p
        join raw_picks rp on rp.id = p.raw_pick_id
        join sources s on s.id = rp.source_id
        where p.status = 'revisao_manual' and p.fixture_id = any(%s::uuid[]) and s.quarentena is not true
        """,
        (fixture_ids,),
    )
    conflitos: dict[tuple[str, str], list[tuple[str, str, str | None]]] = {}
    for fixture_id, mercado, pick_id, selecao, tipster in cur.fetchall():
        conflitos.setdefault((str(fixture_id), mercado), []).append((str(pick_id), selecao, tipster))
    return conflitos


def excluidos_do_dia(cur: psycopg.Cursor, fixture_ids: list[str]) -> list[tuple[str, str, str | None, str | None]]:
    if not fixture_ids:
        return []
    cur.execute(
        """
        select po.pick_id, po.motivo, p.time_casa, p.time_fora
        from picks_orfaos po
        join picks p on p.id = po.pick_id
        where po.tipo = 'excluido' and p.fixture_id = any(%s::uuid[])
        """,
        (fixture_ids,),
    )
    return [(str(pick_id), motivo, time_casa, time_fora) for pick_id, motivo, time_casa, time_fora in cur.fetchall()]


@dataclass(frozen=True)
class MensagemNaFila:
    message_id: str
    user_id: str
    nome: str | None
    telefone_e164: str
    tipo: str
    # None pra tipo='resumo_semanal' (Fase 6e) - mensagem agregada da
    # semana, sem partida associada (messages.fixture_id e' nullable
    # desde migrations/0027_messages_resumo_semanal.sql).
    fixture_id: str | None
    time_casa: str | None
    time_fora: str | None
    kickoff_utc: datetime | None
    corpo_renderizado: str
    gerada_em: datetime


def fila_envio(cur: psycopg.Cursor) -> list[MensagemNaFila]:
    # SQL_ASSINANTE_ATIVO importado de app.subs, nunca reescrito - mesmo
    # predicado do teto de assinantes (Fase 5b). registrar_opt_out ja
    # marca as mensagens 'pronta' do usuario como 'pulada', mas essa
    # fila nao deve depender so disso pra nao repetir o CRITICAL de
    # quarentena da Fase 5c (garantia no dado, nao so na exibicao).
    #
    # LEFT JOIN fixtures (Fase 6e): mensagem de tipo='resumo_semanal' tem
    # fixture_id NULL por design - um INNER JOIN puro a excluiria da fila
    # inteira, qualquer que fosse o filtro. "nulls last" pra nao intercalar
    # resumos semanais no meio da ordem por kickoff das demais.
    cur.execute(
        f"""
        select m.id, m.user_id, u.nome, u.telefone_e164, m.tipo, f.id, tc.nome_canonico, tf.nome_canonico,
               f.kickoff_utc, m.corpo_renderizado, m.gerada_em
        from messages m
        join users u on u.id = m.user_id
        left join fixtures f on f.id = m.fixture_id
        left join teams tc on tc.id = f.home_team_id
        left join teams tf on tf.id = f.away_team_id
        where m.status = 'pronta' and {SQL_ASSINANTE_ATIVO}
        order by f.kickoff_utc nulls last, m.gerada_em
        """
    )
    return [
        MensagemNaFila(
            message_id=str(row[0]), user_id=str(row[1]), nome=row[2], telefone_e164=row[3], tipo=row[4],
            fixture_id=str(row[5]) if row[5] is not None else None, time_casa=row[6], time_fora=row[7],
            kickoff_utc=row[8], corpo_renderizado=row[9], gerada_em=row[10],
        )
        for row in cur.fetchall()
    ]


@dataclass(frozen=True)
class ContadoresEnvio:
    prontas: int
    enviadas_hoje: int
    expirando_2h: int


@dataclass(frozen=True)
class SessaoEnvio:
    id: str
    data: date
    slate_id: str
    status: str
    iniciada_em: datetime
    pausada_em: datetime | None
    retomada_em: datetime | None
    encerrada_em: datetime | None


def buscar_sessao_aberta(cur: psycopg.Cursor, data_sessao: date) -> SessaoEnvio | None:
    # "order by iniciada_em desc limit 1" e defesa em profundidade - o
    # indice parcial (migration 0021) ja garante no maximo 1 linha com
    # encerrada_em is null por data.
    cur.execute(
        """
        select id, data, slate_id, status, iniciada_em, pausada_em, retomada_em, encerrada_em
        from envio_sessoes
        where data = %s and encerrada_em is null
        order by iniciada_em desc
        limit 1
        """,
        (data_sessao,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    # str() explicito em id/slate_id - mesmo bug real da Fase 5d
    # (buscar_slate_atual): psycopg devolve coluna uuid como uuid.UUID,
    # e uuid.UUID.__eq__(str) nunca e True, o que quebraria toda
    # comparacao de gate contra o path param (sempre string).
    sessao_id, data_row, slate_id, status, iniciada_em, pausada_em, retomada_em, encerrada_em = row
    return SessaoEnvio(
        id=str(sessao_id), data=data_row, slate_id=str(slate_id), status=status,
        iniciada_em=iniciada_em, pausada_em=pausada_em, retomada_em=retomada_em, encerrada_em=encerrada_em,
    )


def universo_da_sessao(cur: psycopg.Cursor, data_sessao: date) -> list[str]:
    # Universo ESTAVEL do dia (D19) - todo assinante ativo que ja teve
    # mensagem gerada hoje, em qualquer status, nao so quem ainda esta
    # 'pronta'. Sem isso, ordem_da_sessao reembaralharia a fila a cada
    # mensagem resolvida (n muda, offset muda) - achado central do plano
    # da Fase 5d-D. `slate_id in (...)` cobre a cadeia de correcao (todo
    # slate de uma correcao compartilha a mesma data); `status = 'pronta'`
    # cobre o caso defensivo de mensagem de outro dia/slate que
    # fila_envio ainda mostraria (fila_envio nao filtra por data).
    #
    # Achado real (checklist manual de navegador, Fase 6e+): mensagem de
    # `tipo='fechamento'` (Fase 6e) tem `slate_id` sempre NULL - por
    # design, ela nao pertence a slate nenhum. Sem o terceiro termo do OR
    # abaixo, um assinante cuja UNICA mensagem do dia fosse um fechamento
    # cairia do universo assim que ela deixasse de estar 'pronta'
    # (resolvida) - reintroduzindo, so pra fechamento, o mesmo
    # reembaralhamento que os dois primeiros termos existem pra evitar.
    # `limites_utc_do_dia` (nao `gerada_em::date`) pelo mesmo motivo de
    # `app.relatorio_diario`: `::date` avalia no fuso da sessao do
    # Postgres (UTC), nao em America/Sao_Paulo.
    inicio_utc, fim_utc = limites_utc_do_dia(data_sessao)
    cur.execute(
        f"""
        select distinct m.user_id
        from messages m
        join users u on u.id = m.user_id
        where {SQL_ASSINANTE_ATIVO}
          and (
            m.status = 'pronta'
            or m.slate_id in (select id from daily_slates where data = %s)
            or (m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s)
          )
        order by 1
        """,
        (data_sessao, inicio_utc, fim_utc),
    )
    return [str(row[0]) for row in cur.fetchall()]


def resumo_do_dia(cur: psycopg.Cursor, data_sessao: date) -> tuple[int, int, int, list[tuple[str | None, str, str]]]:
    # Escopo e o DIA (via daily_slates.data), nao a sessao - se o
    # operador encerrar e abrir uma segunda sessao no mesmo dia (D17), o
    # resumo continua cobrindo o dia inteiro, nao so a sessao atual.
    #
    # LEFT JOIN + segundo termo do OR (achado real, mesma classe do bug
    # de universo_da_sessao acima): um INNER JOIN puro em daily_slates
    # exclui TODA mensagem de fechamento (slate_id NULL por design,
    # Fase 6e) do resumo - confirmado ao vivo nesta sessao, uma
    # mensagem de fechamento marcada 'enviada' pelo atalho Enter
    # aparecia como "Enviadas: 0" no resumo de fim de sessao, apesar do
    # dado em `messages.status` estar correto.
    inicio_utc, fim_utc = limites_utc_do_dia(data_sessao)
    cur.execute(
        """
        select
            count(*) filter (where m.status = 'enviada') as enviadas,
            count(*) filter (where m.status = 'expirada') as expiradas,
            count(*) filter (where m.status = 'pronta') as prontas_restantes
        from messages m
        left join daily_slates ds on ds.id = m.slate_id
        where ds.data = %s or (m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s)
        """,
        (data_sessao, inicio_utc, fim_utc),
    )
    enviadas, expiradas, prontas_restantes = cur.fetchone()

    cur.execute(
        """
        select u.nome, u.telefone_e164, m.motivo_pulo
        from messages m
        left join daily_slates ds on ds.id = m.slate_id
        join users u on u.id = m.user_id
        where (ds.data = %s or (m.slate_id is null and m.gerada_em >= %s and m.gerada_em < %s))
          and m.status = 'pulada'
        """,
        (data_sessao, inicio_utc, fim_utc),
    )
    puladas = [(nome, telefone, motivo) for nome, telefone, motivo in cur.fetchall()]

    return enviadas, expiradas, prontas_restantes, puladas


def contadores_do_dia(cur: psycopg.Cursor, agora: datetime) -> ContadoresEnvio:
    # LEFT JOIN fixtures (Fase 6e): um INNER JOIN puro excluiria mensagem
    # de tipo='resumo_semanal' (fixture_id NULL) de TODOS os contadores,
    # nao so' de expirando_2h - inclusive de "prontas"/"enviadas_hoje",
    # onde ela devia contar normalmente. `f.kickoff_utc <= ...` com
    # kickoff_utc NULL avalia pra desconhecido/falso em SQL, entao
    # expirando_2h ja exclui resumo semanal sem precisar de guarda extra.
    cur.execute(
        f"""
        select
            count(*) filter (where m.status = 'pronta') as prontas,
            count(*) filter (where m.status = 'enviada' and m.enviada_em::date = %s::date) as enviadas_hoje,
            count(*) filter (
                where m.status = 'pronta' and f.kickoff_utc <= %s + interval '2 hours'
            ) as expirando_2h
        from messages m
        left join fixtures f on f.id = m.fixture_id
        join users u on u.id = m.user_id
        where {SQL_ASSINANTE_ATIVO}
        """,
        (agora, agora),
    )
    prontas, enviadas_hoje, expirando_2h = cur.fetchone()
    return ContadoresEnvio(prontas=prontas, enviadas_hoje=enviadas_hoje, expirando_2h=expirando_2h)


def carregar_dashboard_saude(cur: psycopg.Cursor, hoje: date, estado: "EstadoRun") -> dict:
    """Agregador de dados para a aba Saude e Controle.

    `estado` vem de fora (dependencia `estado_run_hoje`, ja resolvida pela
    rota) em vez de ser recalculado aqui - evita uma segunda consulta a
    `pipeline_runs`/`pipeline_stages` na mesma requisicao."""
    from app.console.rules import FONTES_COLETA, dias_fora_por_fonte, projetar_quota
    from app.subs import listar_vencendo

    historico = historico_coleta(cur, dias=14)
    chamadas, limite = quota_mes(cur, hoje.strftime("%Y-%m"))

    return {
        "estado": estado,
        "dias_fora_por_fonte": dias_fora_por_fonte(historico, FONTES_COLETA),
        "quota": projetar_quota(chamadas, limite, hoje),
        "orfaos_aguardando_partida": orfaos_aguardando_partida(cur),
        "encerradas_sem_liquidacao": encerradas_sem_liquidacao(cur),
        "mensagens_expiradas": mensagens_expiradas(cur),
        "vencendo": listar_vencendo(cur, hoje=hoje),
    }


def carregar_relatorio_fontes_30d(cur: psycopg.Cursor) -> tuple:
    """Carrega metricas e status de quarentena das fontes dos ultimos 30 dias."""
    from app.settlement.relatorio_fonte import buscar_quarentena_por_fonte, gerar_relatorio_por_fonte

    desde = datetime.now(timezone.utc) - timedelta(days=30)
    metricas = gerar_relatorio_por_fonte(cur, desde=desde)
    quarentena = buscar_quarentena_por_fonte(cur)
    return metricas, quarentena
