"""Assinaturas manuais via Pix (Fase 5b, ver "Controle de acesso" e
"Teto operacional" no documento original).

O teto de MAX_ASSINANTES_ATIVOS e trava dura, nao sugestao ("Implemente
como validacao dura... Nao e sugestao, e trava"). "Assinante ativo" e
definido como o PICO de assinantes distintos em qualquer dia do periodo
da assinatura sendo registrada, contando essa assinatura como se ja
existisse (`pico_assinantes_no_periodo`) - nao so "quem tem assinatura
cobrindo hoje". Duas propriedades dependem disso:

1. Alguem com duas assinaturas sobrepostas ocupa uma vaga so (uma
   mensagem de WhatsApp por dia por pessoa) - por isso `count(distinct
   user_id)`, nunca `count(*)`.
2. Uma renovacao de quem ja esta ativo nunca pode ser recusada por
   estar exatamente no limite - por isso a assinatura candidata entra
   no UNION ALL antes da deduplicacao: um usuario ja ativo renovando
   nao muda a contagem daquele dia.

Decisao tomada com o PM (D2, ver CLAUDE.md Fase 5b): pico no periodo,
nao so "cobre hoje" - a leitura mais simples deixaria passar estourar o
teto num mes futuro mesmo com a lista de hoje cheia.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal

import psycopg
import psycopg.errors

from app.users import buscar_usuario_por_id

# Predicado canonico de "assinante ativo" - usado pelo teto
# (pico_assinantes_no_periodo) e pelo painel de vencimento
# (listar_vencendo). Um quarto consumidor (Fase 5c/5d, geracao de
# mensagem) deve importar esta constante, nunca reescrever o predicado -
# mesma licao da duplicacao de upsert_source pega na revisao holistica
# pos-Fase 2.
SQL_ASSINANTE_ATIVO = "u.opt_out_em is null and u.status = 'ativo'"

DIAS_AVISO_VENCIMENTO = 5


class PeriodoInvalido(ValueError):
    pass


class UsuarioInexistente(ValueError):
    pass


class UsuarioOptOut(ValueError):
    pass


class ReferenciaPagamentoDuplicada(ValueError):
    pass


class TetoExcedido(Exception):
    def __init__(self, dia: date, quantidade: int, teto: int):
        self.dia = dia
        self.quantidade = quantidade
        self.teto = teto
        super().__init__(f"teto de assinantes ativos excedido em {dia}: {quantidade}/{teto}")


def validar_periodo(inicio: date, fim: date) -> None:
    if fim < inicio:
        raise PeriodoInvalido(f"fim ({fim}) antes do inicio ({inicio})")


def cabe_no_teto(pico: int, teto: int) -> bool:
    return pico <= teto


@dataclass(frozen=True)
class PicoAssinantes:
    dia: date
    quantidade: int


def pico_assinantes_no_periodo(cur: psycopg.Cursor, *, inicio: date, fim: date, user_id_candidato: str) -> PicoAssinantes:
    cur.execute(
        f"""
        with periodo as (
            select generate_series(%s::date, %s::date, interval '1 day')::date as dia
        ),
        vigentes as (
            select s.user_id, s.inicio, s.fim
            from subscriptions s
            join users u on u.id = s.user_id
            where {SQL_ASSINANTE_ATIVO}
            union all
            select %s::uuid, %s::date, %s::date
        )
        select p.dia, count(distinct v.user_id) as qtd
        from periodo p
        join vigentes v on p.dia between v.inicio and v.fim
        group by p.dia
        order by qtd desc, p.dia asc
        limit 1
        """,
        (inicio, fim, user_id_candidato, inicio, fim),
    )
    dia, quantidade = cur.fetchone()
    return PicoAssinantes(dia=dia, quantidade=quantidade)


def registrar_assinatura(
    cur: psycopg.Cursor,
    *,
    user_id: str,
    inicio: date,
    fim: date,
    valor: Decimal,
    meio_pagamento: str,
    referencia_pagamento: str | None,
    registrado_por: str,
    teto: int,
) -> str:
    validar_periodo(inicio, fim)

    usuario = buscar_usuario_por_id(cur, user_id)
    if usuario is None:
        raise UsuarioInexistente(f"usuario nao encontrado: {user_id}")
    if usuario.opt_out_em is not None:
        raise UsuarioOptOut(f"usuario optou por sair, nao pode receber assinatura nova: {user_id}")

    pico = pico_assinantes_no_periodo(cur, inicio=inicio, fim=fim, user_id_candidato=user_id)
    if not cabe_no_teto(pico.quantidade, teto):
        raise TetoExcedido(pico.dia, pico.quantidade, teto)

    try:
        cur.execute(
            """
            insert into subscriptions (user_id, inicio, fim, valor, meio_pagamento, referencia_pagamento, registrado_por)
            values (%s::uuid, %s, %s, %s, %s, %s, %s)
            returning id
            """,
            (user_id, inicio, fim, valor, meio_pagamento, referencia_pagamento, registrado_por),
        )
    except psycopg.errors.UniqueViolation as exc:
        # uq_subscriptions_referencia_pagamento (migration 0017) - o erro
        # cru do driver vaza o nome interno da constraint pro operador;
        # aqui vira uma mensagem que explica o que aconteceu de verdade
        # (rodar o mesmo `registrar` duas vezes e o erro humano real que
        # essa constraint existe pra pegar, nao concorrencia).
        raise ReferenciaPagamentoDuplicada(
            f"referencia de pagamento ja usada em outra assinatura: {referencia_pagamento!r}"
        ) from exc
    return str(cur.fetchone()[0])


@dataclass(frozen=True)
class AssinaturaVencendo:
    user_id: str
    nome: str | None
    telefone_e164: str
    fim: date
    dias_restantes: int
    valor: Decimal
    ja_renovado: bool


def listar_vencendo(cur: psycopg.Cursor, *, hoje: date, dias: int = DIAS_AVISO_VENCIMENTO) -> list[AssinaturaVencendo]:
    limite = hoje + timedelta(days=dias)
    cur.execute(
        f"""
        select u.id, u.nome, u.telefone_e164, s.fim, s.valor,
               exists(
                   select 1 from subscriptions s2
                   where s2.user_id = s.user_id and s2.inicio > s.fim
               ) as ja_renovado
        from subscriptions s
        join users u on u.id = s.user_id
        where {SQL_ASSINANTE_ATIVO} and s.fim between %s and %s
        order by s.fim asc
        """,
        (hoje, limite),
    )
    return [
        AssinaturaVencendo(
            user_id=str(row[0]), nome=row[1], telefone_e164=row[2], fim=row[3],
            dias_restantes=(row[3] - hoje).days, valor=row[4], ja_renovado=row[5],
        )
        for row in cur.fetchall()
    ]
