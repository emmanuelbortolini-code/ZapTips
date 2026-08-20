"""Geracao de mensagens de resumo semanal (Fase 6e, ultimo pedaco) - agrega
`bets` da semana operacional anterior (segunda a domingo, ver
app.pipeline.segunda_da_semana_anterior) por usuario e gera uma mensagem
por (usuario, semana), `tipo='resumo_semanal'`, SEM fixture - mensagem
agregada, nao aponta pra uma partida especifica (`messages.fixture_id` e
nullable desde migrations/0027_messages_resumo_semanal.sql, criada pra
viabilizar isso).

So gera resumo pra usuario com pelo menos 1 aposta na semana - sem
atividade, uma mensagem "0 palpites" nao agregaria nada pro assinante e
so encheria a fila de envio a toa.

Idempotencia: chave propria (prefixo "resumo_semanal"), escopada pela
DATA DE INICIO da semana (segunda), nao pela data de execucao do job -
mesmo raciocinio de app.fechamento_generator (chave separada da de
palpite, nunca reaproveitando o formato de outra funcao que dado real ja
depende). Rodar atrasado (ex. terca, se o agendador ficou fora do ar na
segunda) usa a mesma segunda calculada por
app.pipeline.segunda_da_semana_anterior e cai no mesmo idempotency_key -
nunca duplica, nunca pula a semana.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

import psycopg

from app.messaging import ContextoResumoSemanal, renderizar_resumo_semanal
from app.pipeline import limites_utc_do_dia
from app.settlement.banca import Aposta
from app.settlement.extrato_usuario import buscar_config_banca
from app.settlement.resumo_semanal import calcular_resumo_semanal

_SQL_USUARIOS_COM_APOSTA_NA_SEMANA = """
    select distinct b.user_id
    from bets b
    join fixtures f on f.id = b.fixture_id
    where f.kickoff_utc >= %s and f.kickoff_utc < %s
    order by 1
"""

_SQL_APOSTAS_DA_SEMANA = """
    select b.pick_id, b.fixture_id, b.message_id, b.odd, b.stake_valor, b.stake_pct,
           b.resultado, b.retorno, b.banca_antes, b.banca_depois, b.sequencia
    from bets b
    join fixtures f on f.id = b.fixture_id
    where b.user_id = %s::uuid and f.kickoff_utc >= %s and f.kickoff_utc < %s
    order by b.sequencia
"""

_SQL_BANCA_ANTES_DA_SEMANA = """
    select b.banca_depois
    from bets b
    join fixtures f on f.id = b.fixture_id
    where b.user_id = %s::uuid and f.kickoff_utc < %s
    order by b.sequencia desc
    limit 1
"""

# Mesmo criterio de "efetivamente enviado" ja usado em
# app.settlement.relatorio_usuario._SQL_NAO_LIQUIDADOS_PERIODO, so que
# limitado a tipo='palpite' (fechamento/resumo_semanal nao carregam pick
# original vinculavel do mesmo jeito) e com janela fechada dos dois
# lados (semana especifica, nao "desde X ate agora").
_SQL_NAO_LIQUIDADOS_DA_SEMANA = """
    select count(distinct p.id)
    from messages m
    join fixtures f on f.id = m.fixture_id
    join picks p on p.fixture_id = f.id and p.id = any(m.pick_ids)
    join pick_results pr on pr.pick_id = p.id and pr.resultado = 'nao_liquidavel'
    where m.user_id = %s::uuid and m.tipo = 'palpite'
      and m.status = 'enviada' and m.enviada_em is not null and m.enviada_em < f.kickoff_utc
      and f.kickoff_utc >= %s and f.kickoff_utc < %s
"""


@dataclass(frozen=True)
class JanelaSemana:
    inicio_semana: date
    inicio_utc: datetime
    fim_utc: datetime


def montar_janela_semana(inicio_semana: date) -> JanelaSemana:
    # Janela = [segunda 00h BRT, domingo seguinte 23h59 BRT] -> em UTC,
    # [limites_utc_do_dia(segunda)[0], limites_utc_do_dia(segunda+6)[1]).
    inicio_utc, _ = limites_utc_do_dia(inicio_semana)
    _, fim_utc = limites_utc_do_dia(inicio_semana + timedelta(days=6))
    return JanelaSemana(inicio_semana=inicio_semana, inicio_utc=inicio_utc, fim_utc=fim_utc)


def montar_idempotency_key_resumo_semanal(user_id: str, inicio_semana: date) -> str:
    base = f"resumo_semanal|{user_id}|{inicio_semana.isoformat()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


def buscar_usuarios_com_atividade_na_semana(cur: psycopg.Cursor, janela: JanelaSemana) -> list[str]:
    cur.execute(_SQL_USUARIOS_COM_APOSTA_NA_SEMANA, (janela.inicio_utc, janela.fim_utc))
    return [str(row[0]) for row in cur.fetchall()]


def _buscar_apostas_da_semana(cur: psycopg.Cursor, user_id: str, janela: JanelaSemana) -> list[Aposta]:
    cur.execute(_SQL_APOSTAS_DA_SEMANA, (user_id, janela.inicio_utc, janela.fim_utc))
    apostas = []
    for pick_id, fixture_id, message_id, odd, stake_valor, stake_pct, resultado, retorno, banca_antes, banca_depois, sequencia in cur.fetchall():
        apostas.append(
            Aposta(
                pick_id=str(pick_id), fixture_id=str(fixture_id), message_id=str(message_id) if message_id else None,
                odd=Decimal(str(odd)), stake_valor=Decimal(str(stake_valor)), stake_pct=Decimal(str(stake_pct)),
                resultado=resultado, retorno=Decimal(str(retorno)), banca_antes=Decimal(str(banca_antes)),
                banca_depois=Decimal(str(banca_depois)), sequencia=sequencia,
            )
        )
    return apostas


def _buscar_banca_no_inicio_da_semana(cur: psycopg.Cursor, user_id: str, janela: JanelaSemana, settings) -> Decimal:
    cur.execute(_SQL_BANCA_ANTES_DA_SEMANA, (user_id, janela.inicio_utc))
    row = cur.fetchone()
    if row is not None:
        return Decimal(str(row[0]))
    banca_inicial, _stake_pct, _modo_stake = buscar_config_banca(cur, user_id, settings)
    return banca_inicial


def _contar_nao_liquidados_da_semana(cur: psycopg.Cursor, user_id: str, janela: JanelaSemana) -> int:
    cur.execute(_SQL_NAO_LIQUIDADOS_DA_SEMANA, (user_id, janela.inicio_utc, janela.fim_utc))
    return cur.fetchone()[0]


def _nome_do_usuario(cur: psycopg.Cursor, user_id: str) -> str:
    cur.execute("select nome from users where id = %s::uuid", (user_id,))
    nome = cur.fetchone()[0]
    return nome or "assinante"


def gerar_resumos_semanais(cur: psycopg.Cursor, inicio_semana: date, rodape_legal: str, settings) -> int:
    janela = montar_janela_semana(inicio_semana)
    fim_semana = inicio_semana + timedelta(days=6)

    gerados = 0
    for user_id in buscar_usuarios_com_atividade_na_semana(cur, janela):
        apostas = _buscar_apostas_da_semana(cur, user_id, janela)
        banca_no_inicio = _buscar_banca_no_inicio_da_semana(cur, user_id, janela, settings)
        nao_liquidados = _contar_nao_liquidados_da_semana(cur, user_id, janela)
        resumo = calcular_resumo_semanal(apostas, banca_no_inicio_semana=banca_no_inicio, nao_liquidados=nao_liquidados)

        contexto = ContextoResumoSemanal(
            primeiro_nome=_nome_do_usuario(cur, user_id),
            inicio_semana=inicio_semana.strftime("%d/%m"),
            fim_semana=fim_semana.strftime("%d/%m"),
            total_palpites=resumo.total_palpites, greens=resumo.greens, reds=resumo.reds,
            banca_inicial=resumo.banca_inicial, banca_atual=resumo.banca_atual,
            roi=resumo.roi, nao_liquidados=resumo.nao_liquidados, rodape_legal=rodape_legal,
        )
        corpo = renderizar_resumo_semanal(contexto)
        idempotency_key = montar_idempotency_key_resumo_semanal(user_id, inicio_semana)
        pick_ids = [a.pick_id for a in apostas]

        cur.execute(
            """
            insert into messages (user_id, fixture_id, pick_ids, corpo_renderizado, idempotency_key, tipo)
            values (%s::uuid, null, %s::uuid[], %s, %s, 'resumo_semanal')
            on conflict (idempotency_key) do nothing
            returning id
            """,
            (user_id, pick_ids, corpo, idempotency_key),
        )
        if cur.fetchone() is not None:
            gerados += 1

    return gerados
