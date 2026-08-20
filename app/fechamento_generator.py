"""Geracao de mensagens de fechamento do palpite (Fase 6e) - le `bets`
(Fase 6b, extrato ja calculado por usuario) e gera uma mensagem por
(usuario, fixture) com o resultado de cada pick + a banca simulada apos
essas apostas. Mesma fila que as mensagens de palpite (`messages`, agora
com `tipo='fechamento'` - ver migrations/0026_messages_tipo.sql).

"Algumas horas apos o jogo" (spec) sai de graca da latencia natural do
pipeline: uma linha em `bets` so existe depois que fixture encerra,
liquida (Fase 6a) e o extrato do usuario e recalculado (Fase 6b) - nao
precisa de um atraso explicito adicional.

Idempotencia: NAO reaproveita app.messages_generator.
montar_idempotency_key (ja em producao, sem `tipo`) - uma chave separada
com prefixo proprio e' mais seguro que alterar o formato de uma funcao
que dado real ja depende, e garante que 'palpite'/'fechamento' pra
mesma (user, fixture, data) nunca colidem.

Limitacao conhecida, aceita (achado MEDIUM do code-reviewer): o gate
"ja tem fechamento?" em `_SQL_APOSTAS_PENDENTES` e' por (user_id,
fixture_id) inteiro, nao por pick. Se uma correcao de slate adicionar
um pick NOVO pra uma fixture que ja recebeu fechamento (bets rebuild
via app.settlement.extrato_usuario.gravar_extrato, delete+insert
completo), esse pick novo nunca gera um fechamento proprio - fica
permanentemente omitido, nunca duplicado. Cenario raro (exige uma
correcao depois do jogo ja ter sido liquidado e mensageado) - nao
resolvido especulativamente sem ver se acontece de verdade, mesmo
criterio ja aplicado ao resto do projeto pra edge cases raros.
"""

import hashlib
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import psycopg

from app.messaging import ContextoFechamento, PalpiteFechado, renderizar_fechamento

_SQL_APOSTAS_PENDENTES = """
    select b.user_id, b.fixture_id, tc.nome_canonico, tf.nome_canonico, f.placar_casa, f.placar_fora,
           b.pick_id, p.selecao, b.odd, b.resultado, b.banca_antes, b.banca_depois
    from bets b
    join fixtures f on f.id = b.fixture_id
    join teams tc on tc.id = f.home_team_id
    join teams tf on tf.id = f.away_team_id
    join picks p on p.id = b.pick_id
    where not exists (
        select 1 from messages m
        where m.user_id = b.user_id and m.fixture_id = b.fixture_id and m.tipo = 'fechamento'
    )
    order by b.user_id, b.fixture_id, b.sequencia
"""


def montar_idempotency_key_fechamento(user_id: str, fixture_id: str, data: date) -> str:
    base = f"fechamento|{user_id}|{fixture_id}|{data.isoformat()}"
    return hashlib.sha256(base.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ApostaParaFechamento:
    pick_id: str
    selecao: str
    odd: Decimal
    resultado: str
    banca_antes: Decimal
    banca_depois: Decimal


@dataclass(frozen=True)
class GrupoFechamento:
    user_id: str
    fixture_id: str
    time_casa: str
    time_fora: str
    placar_casa: int
    placar_fora: int
    apostas: tuple[ApostaParaFechamento, ...]


def buscar_grupos_pendentes(cur: psycopg.Cursor) -> list[GrupoFechamento]:
    cur.execute(_SQL_APOSTAS_PENDENTES)

    grupos: list[GrupoFechamento] = []
    apostas_atuais: list[ApostaParaFechamento] = []
    chave_atual: tuple[str, str] | None = None
    cabecalho_atual: tuple[str, str, int, int] | None = None

    def _fechar_grupo() -> None:
        if chave_atual is None:
            return
        user_id, fixture_id = chave_atual
        time_casa, time_fora, placar_casa, placar_fora = cabecalho_atual
        grupos.append(
            GrupoFechamento(
                user_id=user_id, fixture_id=fixture_id, time_casa=time_casa, time_fora=time_fora,
                placar_casa=placar_casa, placar_fora=placar_fora, apostas=tuple(apostas_atuais),
            )
        )

    for row in cur.fetchall():
        user_id, fixture_id, time_casa, time_fora, placar_casa, placar_fora, pick_id, selecao, odd, resultado, banca_antes, banca_depois = row
        chave = (str(user_id), str(fixture_id))
        if chave != chave_atual:
            _fechar_grupo()
            chave_atual = chave
            cabecalho_atual = (time_casa, time_fora, placar_casa, placar_fora)
            apostas_atuais = []
        apostas_atuais.append(
            ApostaParaFechamento(
                pick_id=str(pick_id), selecao=selecao, odd=Decimal(str(odd)), resultado=resultado,
                banca_antes=Decimal(str(banca_antes)), banca_depois=Decimal(str(banca_depois)),
            )
        )
    _fechar_grupo()

    return grupos


def gerar_fechamentos(cur: psycopg.Cursor, data: date, rodape_legal: str) -> int:
    grupos = buscar_grupos_pendentes(cur)

    gerados = 0
    for grupo in grupos:
        # variacao = soma do delta de CADA aposta (banca_depois -
        # banca_antes daquela linha), nunca "ultima banca_depois menos
        # primeira banca_antes" (achado HIGH do code-reviewer, Fase 6e):
        # `bets.sequencia` e' GLOBAL por usuario, ordenada por
        # (kickoff_utc, pick_id) de TODAS as fixtures
        # (app.settlement.banca.ordenar_deterministico) - duas apostas
        # da MESMA fixture nao sao necessariamente adjacentes nessa
        # sequencia se outra fixture do usuario comecar no mesmo
        # horario. Somar o delta linha a linha e' imune a isso.
        banca_atual = grupo.apostas[-1].banca_depois
        variacao = sum((a.banca_depois - a.banca_antes for a in grupo.apostas), Decimal("0"))

        contexto = ContextoFechamento(
            time_casa=grupo.time_casa, time_fora=grupo.time_fora,
            placar_casa=grupo.placar_casa, placar_fora=grupo.placar_fora,
            palpites=tuple(
                PalpiteFechado(selecao=a.selecao, odd=a.odd, resultado=a.resultado) for a in grupo.apostas
            ),
            banca_atual=banca_atual, variacao=variacao, rodape_legal=rodape_legal,
        )
        corpo = renderizar_fechamento(contexto)
        idempotency_key = montar_idempotency_key_fechamento(grupo.user_id, grupo.fixture_id, data)
        pick_ids = [a.pick_id for a in grupo.apostas]

        cur.execute(
            """
            insert into messages (user_id, fixture_id, pick_ids, corpo_renderizado, idempotency_key, tipo)
            values (%s::uuid, %s::uuid, %s::uuid[], %s, %s, 'fechamento')
            on conflict (idempotency_key) do nothing
            returning id
            """,
            (grupo.user_id, grupo.fixture_id, pick_ids, corpo, idempotency_key),
        )
        if cur.fetchone() is not None:
            gerados += 1

    return gerados
