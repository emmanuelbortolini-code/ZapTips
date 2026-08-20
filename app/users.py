"""Identidade, consentimento e exportacao LGPD de assinantes (Fase 5b).

"Nenhum numero entra na lista sem registro de opt-in com data, origem e
evidencia" (documento original) - `criar_usuario` exige os tres campos,
e o banco trava com NOT NULL desde a migration 0017 (segura porque
`users` estava comprovadamente vazia no momento da migration - decisao
tomada com o PM, ver CLAUDE.md Fase 5b).

Telefone e sempre normalizado pra E.164 antes de gravar OU consultar
(`normalizar_telefone_e164`) - sem isso, `+55 11 99999-1111` no cadastro
e `+5511999991111` no opt-out nunca batem, e opt-out reporta sucesso sem
ter encontrado ninguem. Nunca logar telefone bruto (`mascarar_telefone`),
mesmo principio ja usado pra nao logar apiKey em `collect_odds.py`
(Fase 1g).
"""

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg

_E164_RE = re.compile(r"^\+[1-9]\d{7,14}$")
_CARACTERES_DE_FORMATACAO_RE = re.compile(r"[\s\-().]")


class TelefoneInvalido(ValueError):
    pass


class TelefoneJaCadastrado(ValueError):
    pass


def normalizar_telefone_e164(bruto: str) -> str:
    limpo = _CARACTERES_DE_FORMATACAO_RE.sub("", bruto)
    if not _E164_RE.match(limpo):
        raise TelefoneInvalido(f"telefone fora do formato E.164: {bruto!r}")
    return limpo


def mascarar_telefone(e164: str) -> str:
    if len(e164) <= 9:
        return e164[0] + "*" * (len(e164) - 1)
    return e164[:5] + "*" * (len(e164) - 9) + e164[-4:]


@dataclass(frozen=True)
class UsuarioResumo:
    user_id: str
    nome: str | None
    telefone_e164: str
    status: str
    opt_out_em: datetime | None


def criar_usuario(
    cur: psycopg.Cursor,
    *,
    nome: str | None,
    telefone_e164: str,
    fuso_horario: str,
    idioma: str,
    opt_in_origem: str,
    opt_in_evidencia: str,
    opt_in_em: datetime | None = None,
) -> str:
    telefone = normalizar_telefone_e164(telefone_e164)
    cur.execute(
        """
        insert into users (nome, telefone_e164, fuso_horario, idioma, opt_in_em, opt_in_origem, opt_in_evidencia, status)
        values (%s, %s, %s, %s, coalesce(%s, now()), %s, %s, 'ativo')
        on conflict (telefone_e164) do nothing
        returning id
        """,
        (nome, telefone, fuso_horario, idioma, opt_in_em, opt_in_origem, opt_in_evidencia),
    )
    row = cur.fetchone()
    if row is None:
        # Nunca sobrescreve um cadastro existente (mesmo raciocinio de
        # upsert_raw_pick/upsert_source pra dado que nao deve ser
        # silenciosamente atualizado) - um typo no CLI nao pode apagar o
        # registro de consentimento de alguem real.
        raise TelefoneJaCadastrado(f"telefone ja cadastrado: {mascarar_telefone(telefone)}")
    return str(row[0])


def buscar_usuario_por_telefone(cur: psycopg.Cursor, telefone_e164: str) -> UsuarioResumo | None:
    telefone = normalizar_telefone_e164(telefone_e164)
    cur.execute(
        "select id, nome, telefone_e164, status, opt_out_em from users where telefone_e164 = %s",
        (telefone,),
    )
    return _linha_para_usuario_resumo(cur.fetchone())


def buscar_usuario_por_id(cur: psycopg.Cursor, user_id: str) -> UsuarioResumo | None:
    cur.execute(
        "select id, nome, telefone_e164, status, opt_out_em from users where id = %s::uuid",
        (user_id,),
    )
    return _linha_para_usuario_resumo(cur.fetchone())


def _linha_para_usuario_resumo(row) -> UsuarioResumo | None:
    if row is None:
        return None
    return UsuarioResumo(user_id=str(row[0]), nome=row[1], telefone_e164=row[2], status=row[3], opt_out_em=row[4])


def registrar_opt_out(cur: psycopg.Cursor, telefone_e164: str, quando: datetime | None = None) -> int | None:
    telefone = normalizar_telefone_e164(telefone_e164)
    cur.execute(
        """
        update users set opt_out_em = coalesce(opt_out_em, coalesce(%s, now()))
        where telefone_e164 = %s and opt_out_em is null
        returning id
        """,
        (quando, telefone),
    )
    row = cur.fetchone()
    if row is None:
        # Ja estava fora - idempotente, nao move a data nem mexe em
        # mensagens de novo (a primeira chamada ja fez isso).
        return None

    user_id = row[0]
    # "Some do console na hora, inclusive das mensagens ja geradas"
    # (documento original) - messages esta vazia hoje, mas a Fase 5d vai
    # ler status='pronta' pra montar a fila de envio. Escrever isso agora
    # significa que opt-out ja fica correto no dia em que a fila existir.
    cur.execute(
        "update messages set status = 'pulada', motivo_pulo = 'opt_out' where user_id = %s::uuid and status = 'pronta' returning id",
        (user_id,),
    )
    return len(cur.fetchall())


def registrar_opt_in_novamente(
    cur: psycopg.Cursor, telefone_e164: str, *, opt_in_origem: str, opt_in_evidencia: str
) -> str | None:
    telefone = normalizar_telefone_e164(telefone_e164)
    cur.execute(
        """
        update users set opt_out_em = null, opt_in_em = now(), opt_in_origem = %s, opt_in_evidencia = %s
        where telefone_e164 = %s
        returning id
        """,
        (opt_in_origem, opt_in_evidencia, telefone),
    )
    row = cur.fetchone()
    return str(row[0]) if row else None


@dataclass(frozen=True)
class TabelaExport:
    tabela: str
    coluna_link: str
    colunas: tuple[str, ...]


# Toda tabela com FK pra users(id) - derivado de migrations/0001_init.sql.
# tests/test_users_export_cobertura.py varre as migrations e falha se uma
# tabela nova com user_id nao estiver aqui (nem numa allowlist explicita),
# pra a Fase 6 (master_ledger etc.) nao esquecer isso silenciosamente.
EXPORT_TABELAS: tuple[TabelaExport, ...] = (
    TabelaExport(
        "users", "id",
        ("id", "nome", "telefone_e164", "fuso_horario", "idioma", "opt_in_em", "opt_in_origem", "opt_in_evidencia", "opt_out_em", "status"),
    ),
    TabelaExport(
        "subscriptions", "user_id",
        ("id", "inicio", "fim", "valor", "meio_pagamento", "referencia_pagamento", "registrado_em", "registrado_por"),
    ),
    TabelaExport(
        "user_preferences", "user_id",
        ("ligas_excluidas", "mercados_excluidos", "odd_min", "odd_max", "max_msgs_dia", "horario_envio"),
    ),
    TabelaExport(
        "messages", "user_id",
        ("id", "fixture_id", "slate_id", "pick_ids", "corpo_renderizado", "status", "idempotency_key", "gerada_em", "enviada_em", "motivo_pulo"),
    ),
    TabelaExport("user_bankroll_config", "user_id", ("banca_inicial", "stake_pct", "modo_stake", "iniciado_em")),
    TabelaExport(
        "bets", "user_id",
        (
            "id", "message_id", "pick_id", "fixture_id", "odd", "stake_valor", "stake_pct", "resultado",
            "retorno", "banca_antes", "banca_depois", "sequencia", "registrado_em", "liquidado_em",
        ),
    ),
)


def _serializar(valor: Any) -> Any:
    if isinstance(valor, Decimal):
        return str(valor)
    if isinstance(valor, (datetime, date)):
        return valor.isoformat()
    if isinstance(valor, UUID):
        return str(valor)
    return valor


def exportar_dados_usuario(cur: psycopg.Cursor, user_id: str) -> dict:
    # Nomes de tabela/coluna vem so de EXPORT_TABELAS (constante do
    # modulo, sem caminho de entrada de usuario) - nunca de argumento
    # externo, entao interpola-los na SQL aqui e seguro. So o user_id
    # (dado real) e passado como parametro vinculado.
    tabelas: dict[str, list[dict[str, Any]]] = {}
    for tabela_export in EXPORT_TABELAS:
        colunas_sql = ", ".join(tabela_export.colunas)
        cur.execute(
            f"select {colunas_sql} from {tabela_export.tabela} where {tabela_export.coluna_link} = %s",
            (user_id,),
        )
        tabelas[tabela_export.tabela] = [
            {coluna: _serializar(valor) for coluna, valor in zip(tabela_export.colunas, linha)}
            for linha in cur.fetchall()
        ]

    return {
        "user_id": user_id,
        "exportado_em": datetime.now(timezone.utc).isoformat(),
        "tabelas": tabelas,
    }
