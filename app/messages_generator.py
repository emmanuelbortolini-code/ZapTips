"""Motor de geracao de `messages` a partir de slate aprovado + assinantes
reais (Fase 5d) - pre-requisito que nunca existiu antes desta fase (ver
CLAUDE.md, Fase 4: "nao gera messages de verdade... falta o que
renderizar pra alguem de verdade").

Split pure/DB-shape de sempre: este modulo tem a logica de decisao (quem
recebe o que, na ordem de que) sem tocar Postgres. `scripts/
generate_messages.py` e a camada de banco que chama estas funcoes.

Uma mensagem e por (usuario, fixture, data) - `messages.fixture_id` e
escalar e `pick_ids` e array, o que prova que o desenho pretendido e
agrupar todos os palpites daquela partida numa mensagem so (ver
app/messaging.py::ContextoMensagem.palpites).
"""

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Sequence

import psycopg

from app.daily_slates import buscar_slate_atual, existe_pick_quarentena_no_slate
from app.messaging import ContextoMensagem, PalpiteNaMensagem, renderizar_mensagem
from app.subs import SQL_ASSINANTE_ATIVO


def montar_idempotency_key(user_id: str, fixture_id: str, data: date) -> str:
    # Separadores explicitos ("|") - concatenacao crua de uuids+data e a
    # classe de bug em que tuplas diferentes colidem (ex.: user "u1" +
    # fixture "1fix" vs user "u11" + fixture "fix").
    base = f"{user_id}|{fixture_id}|{data.isoformat()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class PreferenciaUsuario:
    ligas_excluidas: tuple[str, ...] = ()
    mercados_excluidos: tuple[str, ...] = ()
    odd_min: float | None = None
    odd_max: float | None = None
    max_msgs_dia: int | None = None


@dataclass(frozen=True)
class ItemParaMensagem:
    pick_id: str
    fixture_id: str
    slate_pick_ordem: int
    liga: str
    mercado: str
    selecao: str
    odd_referencia: float
    odd_minima: float
    fonte_publica: bool
    fonte: str | None
    time_casa: str
    time_fora: str
    competicao: str | None
    kickoff_utc: datetime
    transmissao: str | None


def filtrar_por_preferencia(
    itens: Sequence[ItemParaMensagem], preferencia: PreferenciaUsuario | None
) -> list[ItemParaMensagem]:
    # Usuario sem linha em user_preferences (preferencia is None) recebe
    # o slate completo - criterio de aceite literal da spec (Fase 4).
    # Preferencia so SUBTRAI, nunca adiciona.
    if preferencia is None:
        return list(itens)

    resultado = []
    for item in itens:
        if item.liga in preferencia.ligas_excluidas:
            continue
        if item.mercado in preferencia.mercados_excluidos:
            continue
        # Decimal, nao float, na fronteira de comparacao - mesma
        # convencao de app.odds_resolution.calcular_odd_minima (Fase 4,
        # bug real de precisao binaria) e app.console.rules.
        # divergencia_relativa (achado LOW do code-reviewer, Fase 5d-E:
        # esta comparacao reintroduzia float puro nessa mesma fronteira).
        if preferencia.odd_min is not None and Decimal(str(item.odd_referencia)) < Decimal(str(preferencia.odd_min)):
            continue
        if preferencia.odd_max is not None and Decimal(str(item.odd_referencia)) > Decimal(str(preferencia.odd_max)):
            continue
        resultado.append(item)
    return resultado


@dataclass(frozen=True)
class GrupoFixture:
    fixture_id: str
    time_casa: str
    time_fora: str
    competicao: str | None
    kickoff_utc: datetime
    transmissao: str | None
    itens: tuple[ItemParaMensagem, ...] = field(default_factory=tuple)

    @property
    def prioridade(self) -> int:
        # Menor numero = maior prioridade (ordem do curador em
        # slate_picks, ver app/slate.py). O grupo herda a prioridade do
        # seu melhor pick.
        return min(item.slate_pick_ordem for item in self.itens)


def agrupar_por_fixture(itens: Sequence[ItemParaMensagem]) -> list[GrupoFixture]:
    por_fixture: dict[str, list[ItemParaMensagem]] = {}
    for item in itens:
        por_fixture.setdefault(item.fixture_id, []).append(item)

    grupos = []
    for fixture_id, itens_do_grupo in por_fixture.items():
        primeiro = itens_do_grupo[0]
        grupos.append(
            GrupoFixture(
                fixture_id=fixture_id, time_casa=primeiro.time_casa, time_fora=primeiro.time_fora,
                competicao=primeiro.competicao, kickoff_utc=primeiro.kickoff_utc, transmissao=primeiro.transmissao,
                itens=tuple(itens_do_grupo),
            )
        )
    return grupos


def aplicar_max_msgs_dia(grupos: Sequence[GrupoFixture], limite: int | None) -> list[GrupoFixture]:
    if limite is None:
        return list(grupos)
    ordenados = sorted(grupos, key=lambda g: g.prioridade)
    return ordenados[:limite]


def respeita_antecedencia_minima(kickoff_utc: datetime, agora: datetime, horas: int) -> bool:
    # Nivel B do corte de antecedencia (D2, Fase 5d) - defesa que roda no
    # momento real da geracao, nao so na montagem do slate (nivel A, em
    # scripts/build_slate.py). Necessaria porque o slate aprovado e
    # imutavel: se a aprovacao atrasar ou for uma correcao aprovada mais
    # tarde, o nivel A sozinho nao protege mais ninguem.
    return kickoff_utc >= agora + timedelta(hours=horas)


def ordem_da_sessao(user_ids: Sequence[str], data: date) -> list[str]:
    # Ordem base estavel (sorted) rotacionada por um offset derivado da
    # data - deterministico dentro do dia (mesma lista sempre da o mesmo
    # resultado), roda entre dias, e provadamente justo: cada pessoa
    # ocupa cada posicao exatamente uma vez a cada n dias.
    base = sorted(user_ids)
    n = len(base)
    if n == 0:
        return []
    offset = data.toordinal() % n
    return base[offset:] + base[:offset]


def expirar_mensagens_vencidas(cur: psycopg.Cursor, agora: datetime) -> int:
    # So toca 'pronta' - nunca 'enviada'/'pulada' (mensagem ja resolvida
    # nao muda retroativamente). Disparado por um GET (toda abertura da
    # aba Envio) alem desta chamada dentro da geracao - convergencia
    # idempotente derivada so de relogio + kickoff, sem dado da
    # requisicao, entao e seguro rodar num GET apesar de ser escrita.
    #
    # `tipo = 'palpite'` explicito (achado CRITICAL do code-reviewer,
    # Fase 6e): expirar por "kickoff ja passou" so faz sentido pro
    # palpite (a mensagem perde validade se o jogo ja comecou). Uma
    # mensagem de fechamento (app.fechamento_generator) SEMPRE aponta
    # pra um jogo que ja aconteceu, por definicao - sem esse filtro, ela
    # seria marcada 'expirada' no proprio GET /envio que deveria mostra-la,
    # antes de qualquer operador conseguir ve-la ou envia-la.
    cur.execute(
        """
        update messages m set status='expirada'
        from fixtures f
        where f.id = m.fixture_id and m.status = 'pronta' and m.tipo = 'palpite' and f.kickoff_utc <= %s
        returning m.id
        """,
        (agora,),
    )
    return len(cur.fetchall())


def carregar_itens_para_mensagem(cur: psycopg.Cursor, slate_id: str) -> list[ItemParaMensagem]:
    # time_casa/time_fora vem de teams.nome_canonico, nunca de
    # picks.time_casa/time_fora (texto raspado da fonte) - o nome que
    # vai pra quem paga tem que ser o canonico, nao o que o tipster
    # digitou. transmissao: broadcasts (por fixture, so BR) primeiro,
    # senao broadcast_rules (por liga+dia da semana) - as duas tabelas
    # nunca foram populadas por nenhum coletor (D6, Fase 5d), entao isso
    # sempre devolve None hoje; a linha "Onde assistir" e omitida pelo
    # template (app.messaging) quando for o caso, nunca aparece vazia.
    cur.execute(
        """
        select sp.pick_id, sp.ordem, f.id, f.liga, p.mercado, p.selecao, sp.odd_referencia, sp.odd_minima,
               tc.nome_canonico, tf.nome_canonico, p.competicao, f.kickoff_utc,
               coalesce(
                   (select b.canal from broadcasts b where b.fixture_id = f.id and b.pais = 'BR' limit 1),
                   (select array_to_string(br.canais, ', ') from broadcast_rules br
                    where br.liga = f.liga and br.dia_semana = extract(dow from f.kickoff_utc at time zone 'America/Sao_Paulo')::int
                    limit 1)
               ) as transmissao
        from slate_picks sp
        join picks p on p.id = sp.pick_id
        join fixtures f on f.id = p.fixture_id
        join teams tc on tc.id = f.home_team_id
        join teams tf on tf.id = f.away_team_id
        where sp.slate_id = %s::uuid
        """,
        (slate_id,),
    )
    return [
        ItemParaMensagem(
            pick_id=str(row[0]), slate_pick_ordem=row[1], fixture_id=str(row[2]), liga=row[3],
            mercado=row[4], selecao=row[5], odd_referencia=float(row[6]), odd_minima=float(row[7]),
            fonte_publica=False, fonte=None,
            time_casa=row[8], time_fora=row[9], competicao=row[10], kickoff_utc=row[11], transmissao=row[12],
        )
        for row in cur.fetchall()
    ]


def carregar_assinantes_elegiveis(cur: psycopg.Cursor, data: date) -> list[str]:
    # SQL_ASSINANTE_ATIVO importado de app.subs, nunca reescrito - mesmo
    # predicado do teto de assinantes e do painel "vencendo" (Fase 5b).
    cur.execute(
        f"""
        select distinct u.id
        from users u
        join subscriptions s on s.user_id = u.id
        where {SQL_ASSINANTE_ATIVO} and %s::date between s.inicio and s.fim
        """,
        (data,),
    )
    return [str(row[0]) for row in cur.fetchall()]


def carregar_preferencia(cur: psycopg.Cursor, user_id: str) -> PreferenciaUsuario | None:
    cur.execute(
        "select ligas_excluidas, mercados_excluidos, odd_min, odd_max, max_msgs_dia from user_preferences where user_id = %s::uuid",
        (user_id,),
    )
    row = cur.fetchone()
    if row is None:
        return None
    ligas_excluidas, mercados_excluidos, odd_min, odd_max, max_msgs_dia = row
    return PreferenciaUsuario(
        ligas_excluidas=tuple(ligas_excluidas or ()),
        mercados_excluidos=tuple(mercados_excluidos or ()),
        odd_min=float(odd_min) if odd_min is not None else None,
        odd_max=float(odd_max) if odd_max is not None else None,
        max_msgs_dia=max_msgs_dia,
    )


def carregar_nome_e_fuso(cur: psycopg.Cursor, user_id: str) -> tuple[str, str]:
    cur.execute("select nome, fuso_horario from users where id = %s::uuid", (user_id,))
    nome, fuso_horario = cur.fetchone()
    return (nome or "assinante"), fuso_horario


@dataclass(frozen=True)
class RelatorioGeracao:
    status: str = "ok"
    motivo_pulo: str | None = None
    gerados: int = 0
    ja_existentes: int = 0
    pulados_preferencia: int = 0
    pulados_antecedencia: int = 0


def gerar_mensagens(cur: psycopg.Cursor, data: date, agora: datetime, settings) -> RelatorioGeracao:
    # Kill switch no unico choke point (D1, Fase 5d) - os tres pontos de
    # entrada (aprovacao, CLI, botao "regerar") chamam esta mesma funcao,
    # nenhum deles checa QUEUE_ENABLED por fora.
    if not settings.queue_enabled:
        return RelatorioGeracao(status="pulado", motivo_pulo="queue_disabled")

    expirar_mensagens_vencidas(cur, agora)

    slate_atual = buscar_slate_atual(cur, data)
    if slate_atual is None or slate_atual[1] != "aprovado":
        return RelatorioGeracao(status="pulado", motivo_pulo="slate_nao_aprovado")
    slate_id = slate_atual[0]

    # Defesa em profundidade (mesma familia do CRITICAL da Fase 5c, um
    # nivel acima: aqui e o texto que de fato sai pro assinante pagante).
    if existe_pick_quarentena_no_slate(cur, slate_id):
        return RelatorioGeracao(status="pulado", motivo_pulo="quarentena_no_slate")

    itens_do_slate = carregar_itens_para_mensagem(cur, slate_id)
    if not itens_do_slate:
        return RelatorioGeracao(status="ok")

    gerados = 0
    ja_existentes = 0
    pulados_antecedencia = 0
    pulados_preferencia = 0
    # Grupos que existiriam pra qualquer assinante sem nenhuma
    # preferencia - baseline pra medir quanto cada preferencia realmente
    # cortou (achado MEDIUM do code-reviewer, Fase 5d-E: o campo existia
    # na dataclass mas nunca era incrementado).
    grupos_sem_preferencia = agrupar_por_fixture(itens_do_slate)

    for user_id in carregar_assinantes_elegiveis(cur, data):
        preferencia = carregar_preferencia(cur, user_id)
        filtrados = filtrar_por_preferencia(itens_do_slate, preferencia)
        grupos = agrupar_por_fixture(filtrados)
        limite = preferencia.max_msgs_dia if preferencia else None
        grupos = aplicar_max_msgs_dia(grupos, limite)
        pulados_preferencia += len(grupos_sem_preferencia) - len(grupos)

        primeiro_nome, fuso_horario = carregar_nome_e_fuso(cur, user_id)

        for grupo in grupos:
            if not respeita_antecedencia_minima(grupo.kickoff_utc, agora, settings.antecedencia_minima_horas):
                pulados_antecedencia += 1
                continue

            contexto = ContextoMensagem(
                primeiro_nome=primeiro_nome, time_casa=grupo.time_casa, time_fora=grupo.time_fora,
                competicao=grupo.competicao, kickoff_utc=grupo.kickoff_utc, fuso_horario=fuso_horario,
                transmissao=grupo.transmissao,
                palpites=tuple(
                    PalpiteNaMensagem(
                        selecao=item.selecao, odd_referencia=item.odd_referencia, odd_minima=item.odd_minima,
                        fonte_publica=item.fonte_publica, fonte=item.fonte,
                    )
                    for item in grupo.itens
                ),
                rodape_legal=settings.rodape_legal,
            )
            corpo = renderizar_mensagem(contexto)
            idempotency_key = montar_idempotency_key(user_id, grupo.fixture_id, data)
            pick_ids = [item.pick_id for item in grupo.itens]

            cur.execute(
                """
                insert into messages (user_id, fixture_id, slate_id, pick_ids, corpo_renderizado, idempotency_key)
                values (%s::uuid, %s::uuid, %s::uuid, %s::uuid[], %s, %s)
                on conflict (idempotency_key) do nothing
                returning id
                """,
                (user_id, grupo.fixture_id, slate_id, pick_ids, corpo, idempotency_key),
            )
            if cur.fetchone() is not None:
                gerados += 1
            else:
                ja_existentes += 1

    return RelatorioGeracao(
        status="ok", gerados=gerados, ja_existentes=ja_existentes,
        pulados_antecedencia=pulados_antecedencia, pulados_preferencia=pulados_preferencia,
    )
