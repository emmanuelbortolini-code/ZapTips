"""Guarda de cobertura LGPD: toda tabela com coluna `user_id` (ou a
propria `users`) precisa estar em `app.users.EXPORT_TABELAS`, ou numa
allowlist explicita de "nao tem dado pessoal". Sem isso, uma tabela nova
ligada a usuario (ex.: Fase 6, `master_ledger`) pode nascer e nunca ser
adicionada ao export - e ninguem percebe ate um pedido real de LGPD
chegar incompleto. Varre migrations/*.sql em vez de inspecionar o
Postgres, pra falhar em `pytest` (build time), nao em produção."""

import re
from pathlib import Path

from app.users import EXPORT_TABELAS

_MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"
_CREATE_TABLE_RE = re.compile(r"create table (\w+)\s*\((.*?)\n\);", re.DOTALL)

# Nenhuma tabela hoje tem user_id sem carregar dado pessoal - allowlist
# fica vazia de proposito. Uma tabela genuinamente sem dado pessoal (ex.:
# uma tabela de auditoria so com contadores agregados) entraria aqui,
# com um comentario explicando o porque.
TABELAS_SEM_DADO_PESSOAL: frozenset[str] = frozenset()


def _tabelas_com_user_id() -> set[str]:
    tabelas = set()
    for caminho in _MIGRATIONS_DIR.glob("*.sql"):
        texto = caminho.read_text(encoding="utf-8")
        for nome_tabela, corpo in _CREATE_TABLE_RE.findall(texto):
            if re.search(r"\buser_id\b", corpo):
                tabelas.add(nome_tabela)
    return tabelas


def test_toda_tabela_com_user_id_esta_em_export_tabelas_ou_na_allowlist():
    encontradas = _tabelas_com_user_id()
    cobertas = {t.tabela for t in EXPORT_TABELAS} | TABELAS_SEM_DADO_PESSOAL

    faltando = encontradas - cobertas
    assert not faltando, f"tabela(s) com user_id fora de EXPORT_TABELAS e da allowlist: {faltando}"


def test_scan_encontra_pelo_menos_as_tabelas_conhecidas():
    # Regressao pro proprio regex: se o scan quebrar silenciosamente
    # (ex.: mudanca de formatacao no .sql) e passar a nao achar nada, o
    # teste acima passaria vazio sem checar nada de verdade.
    encontradas = _tabelas_com_user_id()
    assert {"subscriptions", "messages", "bets"} <= encontradas


def test_users_esta_em_export_tabelas():
    # 'users' e a propria identidade, nao tem coluna user_id - o scan
    # acima nunca vai achar ela, entao checa explicitamente aqui.
    assert "users" in {t.tabela for t in EXPORT_TABELAS}
