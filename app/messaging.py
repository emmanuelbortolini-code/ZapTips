"""Renderizacao de mensagem por fixture (Fase 4, "Template"; estendido
na Fase 5d pra multiplos palpites - ver achado #1 do plano da 5d).

Funcao pura, testavel sem usuarios reais no banco. `messages.fixture_id`
e escalar e `messages.pick_ids` e array - o design pretendido e uma
mensagem por (usuario, fixture, data), agrupando todos os palpites
daquela partida no slate (mais de um mercado pra mesma partida), nao uma
mensagem por palpite. `app/messages_generator.py` (Fase 5d) e quem monta
o `ContextoMensagem` a partir de dado real; este modulo so renderiza.

`rodape_legal` e obrigatorio por design: campo sem default no
`ContextoMensagem` (o chamador tem que fornecer) e checado de novo em
tempo de render - "Nao torne esse campo opcional no codigo" (documento
original) e levado a serio nos dois pontos.

`transmissao` e opcional (Fase 5d, D6): `broadcast_rules`/`broadcasts`
nunca foram populadas por nenhum coletor - citar "Onde assistir: -" numa
mensagem paga pareceria descuido, entao a linha inteira e omitida quando
nao ha transmissao conhecida, em vez de aparecer vazia.
"""

import random
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal
from zoneinfo import ZoneInfo

from jinja2 import Environment, StrictUndefined

SAUDACOES = [
    "Fala {{ primeiro_nome }}, olha o jogo de hoje:",
    "E aí {{ primeiro_nome }}, bora de palpite:",
    "Oi {{ primeiro_nome }}! Separei esse aqui pra você:",
    "{{ primeiro_nome }}, saiu o palpite de hoje:",
]

_TEMPLATE_CORPO = """{{ saudacao }}

{{ time_casa }} x {{ time_fora }}
{{ competicao }}
{{ horario_local }}
{% if transmissao %}Onde assistir: {{ transmissao }}
{% endif %}
{% for p in palpites %}
Palpite: {{ p.selecao }}
Odd aproximada: {{ p.odd_referencia }}
Não aposte abaixo de {{ p.odd_minima }}
{% if p.fonte_publica %}Fonte: {{ p.fonte }}
{% endif %}
{% endfor %}
{{ rodape_legal }}"""

_env = Environment(undefined=StrictUndefined, autoescape=False, trim_blocks=True, lstrip_blocks=True)
_template_corpo = _env.from_string(_TEMPLATE_CORPO)


@dataclass(frozen=True)
class PalpiteNaMensagem:
    selecao: str
    odd_referencia: float
    odd_minima: float
    fonte_publica: bool = False
    fonte: str | None = None


@dataclass(frozen=True)
class ContextoMensagem:
    primeiro_nome: str
    time_casa: str
    time_fora: str
    competicao: str | None
    kickoff_utc: datetime
    fuso_horario: str
    transmissao: str | None
    palpites: tuple[PalpiteNaMensagem, ...]
    rodape_legal: str


def formatar_horario_local(kickoff_utc: datetime, fuso_horario: str) -> str:
    local = kickoff_utc.astimezone(ZoneInfo(fuso_horario))
    return local.strftime("%d/%m %H:%M")


def sortear_saudacao() -> str:
    return random.choice(SAUDACOES)


def renderizar_mensagem(contexto: ContextoMensagem, saudacao_template: str | None = None) -> str:
    if not contexto.rodape_legal or not contexto.rodape_legal.strip():
        raise ValueError("rodape_legal e obrigatorio - nunca opcional (documento original, secao Template)")
    if not contexto.palpites:
        raise ValueError("uma mensagem precisa de pelo menos um palpite")

    # Substituicao literal, nao Jinja2: compilar `saudacao_template` como
    # template executaria qualquer expressao `{{ ... }}` embutida nele.
    # Hoje so as 4 strings fixas de SAUDACOES (ou None) chegam aqui, mas
    # se um dia uma saudacao personalizada por assinante (Fase 5) passar
    # por este parametro, ela nunca deve virar codigo executavel -
    # achado do code-reviewer.
    saudacao_bruta = saudacao_template if saudacao_template is not None else sortear_saudacao()
    saudacao = saudacao_bruta.replace("{{ primeiro_nome }}", contexto.primeiro_nome)

    return _template_corpo.render(
        saudacao=saudacao,
        time_casa=contexto.time_casa,
        time_fora=contexto.time_fora,
        competicao=contexto.competicao or "",
        horario_local=formatar_horario_local(contexto.kickoff_utc, contexto.fuso_horario),
        transmissao=contexto.transmissao,
        palpites=contexto.palpites,
        rodape_legal=contexto.rodape_legal,
    )


# --- Fechamento do palpite (Fase 6e) ------------------------------------------
#
# Regras de apresentacao da spec, "obrigatorias no codigo e nao
# configuraveis":
#   1. A palavra "simulada" acompanha toda mencao a banca - por isso
#      "Banca simulada" e' texto LITERAL do template, nunca uma variavel
#      que um chamador poderia substituir sem o qualificador.
#   2. Nenhum texto de projecao/previsao/expectativa de retorno futuro -
#      o template so descreve o que ja aconteceu (placar, resultado,
#      banca ja calculada), nunca o que "pode" ou "deve" acontecer.
#   3. Resultado passado sempre com o periodo que cobre - aqui o
#      "periodo" e' a propria partida (placar_casa/placar_fora
#      identificam qual jogo, sempre presentes no template).
#   4. `rodape_legal` continua obrigatorio - mesma checagem de
#      renderizar_mensagem, nunca relaxada pra este template.
Resultado = Literal["green", "meio_green", "void", "meio_red", "red"]

_EMOJI_RESULTADO: dict[Resultado, str] = {
    "green": "✅",
    "meio_green": "🟢",
    "void": "↩️",
    "meio_red": "🟠",
    "red": "❌",
}

_TEXTO_RESULTADO: dict[Resultado, str] = {
    "green": "Green",
    "meio_green": "Meio Green",
    "void": "Void (stake devolvido)",
    "meio_red": "Meio Red",
    "red": "Red",
}

_TEMPLATE_FECHAMENTO = """{{ time_casa }} {{ placar_casa }} x {{ placar_fora }} {{ time_fora }}

{% for p in palpites %}Palpite: {{ p.selecao }} @ {{ p.odd }}
{{ p.emoji }} {{ p.texto }}

{% endfor %}Banca simulada: R$ {{ banca_atual }} ({{ variacao_sinalizada }})

{{ rodape_legal }}"""

_template_fechamento = _env.from_string(_TEMPLATE_FECHAMENTO)


@dataclass(frozen=True)
class PalpiteFechado:
    selecao: str
    odd: Decimal
    resultado: Resultado


@dataclass(frozen=True)
class ContextoFechamento:
    time_casa: str
    time_fora: str
    placar_casa: int
    placar_fora: int
    palpites: tuple[PalpiteFechado, ...]
    banca_atual: Decimal
    variacao: Decimal
    rodape_legal: str


def formatar_variacao_sinalizada(variacao: Decimal) -> str:
    sinal = "+" if variacao > 0 else ""  # negativo ja carrega o "-" do Decimal
    return f"{sinal}R$ {variacao:.2f}"


def renderizar_fechamento(contexto: ContextoFechamento) -> str:
    if not contexto.rodape_legal or not contexto.rodape_legal.strip():
        raise ValueError("rodape_legal e obrigatorio - nunca opcional (documento original, secao Template)")
    if not contexto.palpites:
        raise ValueError("uma mensagem de fechamento precisa de pelo menos um palpite")

    palpites_para_template = [
        {"selecao": p.selecao, "odd": f"{p.odd:.2f}", "emoji": _EMOJI_RESULTADO[p.resultado], "texto": _TEXTO_RESULTADO[p.resultado]}
        for p in contexto.palpites
    ]

    return _template_fechamento.render(
        time_casa=contexto.time_casa,
        time_fora=contexto.time_fora,
        placar_casa=contexto.placar_casa,
        placar_fora=contexto.placar_fora,
        palpites=palpites_para_template,
        banca_atual=f"{contexto.banca_atual:.2f}",
        variacao_sinalizada=formatar_variacao_sinalizada(contexto.variacao),
        rodape_legal=contexto.rodape_legal,
    )


# --- Resumo semanal (Fase 6e) --------------------------------------------------
#
# Mesmas 4 regras obrigatorias de renderizar_fechamento (spec, secao 6e),
# aplicadas aqui tambem:
#   1. "Banca simulada" e' texto LITERAL do template.
#   2. Nenhuma linguagem de projecao/previsao/expectativa futura.
#   3. Resultado passado sempre com o periodo que cobre - aqui a semana
#      inteira, entao o template identifica as duas datas (inicio/fim),
#      nao so' "da semana" solto.
#   4. `rodape_legal` continua obrigatorio.
_TEMPLATE_RESUMO_SEMANAL = """Fala {{ primeiro_nome }}, fechamento da semana ({{ inicio_semana }} a {{ fim_semana }}):

{{ total_palpites }} palpites, {{ greens }} greens e {{ reds }} reds
Banca simulada: R$ {{ banca_inicial }} -> R$ {{ banca_atual }}
{% if roi_texto %}ROI: {{ roi_texto }}
{% endif %}{% if nao_liquidados %}{{ nao_liquidados }} palpites sem resultado confirmado
{% endif %}
{{ rodape_legal }}"""

_template_resumo_semanal = _env.from_string(_TEMPLATE_RESUMO_SEMANAL)


@dataclass(frozen=True)
class ContextoResumoSemanal:
    primeiro_nome: str
    inicio_semana: str
    fim_semana: str
    total_palpites: int
    greens: int
    reds: int
    banca_inicial: Decimal
    banca_atual: Decimal
    roi: Decimal | None
    nao_liquidados: int
    rodape_legal: str


def renderizar_resumo_semanal(contexto: ContextoResumoSemanal) -> str:
    if not contexto.rodape_legal or not contexto.rodape_legal.strip():
        raise ValueError("rodape_legal e obrigatorio - nunca opcional (documento original, secao Template)")
    if contexto.total_palpites < 1:
        raise ValueError("um resumo semanal precisa de pelo menos um palpite na semana")

    return _template_resumo_semanal.render(
        primeiro_nome=contexto.primeiro_nome,
        inicio_semana=contexto.inicio_semana,
        fim_semana=contexto.fim_semana,
        total_palpites=contexto.total_palpites,
        greens=contexto.greens,
        reds=contexto.reds,
        banca_inicial=f"{contexto.banca_inicial:.2f}",
        banca_atual=f"{contexto.banca_atual:.2f}",
        roi_texto=f"{contexto.roi:.2%}" if contexto.roi is not None else None,
        nao_liquidados=contexto.nao_liquidados,
        rodape_legal=contexto.rodape_legal,
    )
