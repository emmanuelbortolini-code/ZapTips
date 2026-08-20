"""Extracao estruturada de palpites via Claude API (Fase 3).

Le raw_picks.texto_bruto (texto livre do tipster) e devolve campos
estruturados: time, competicao, mercado, selecao, odd, casa, unidades,
confianca. Nunca inventa campo - ausente vira None. Um post pode gerar
zero, um ou varios palpites (multiplas selecoes no mesmo texto).

Modelo: Haiku 4.5 (`claude-haiku-4-5`) - decisao do PM. Extracao de campos
curtos de textos curtos e uma tarefa direta de classificacao/extracao, e
este job roda continuamente sobre volume crescente de raw_picks (nao e
uma chamada unica), entao custo por token pesa mais do que numa tarefa de
raciocinio complexo.

Batching: varios posts por chamada (`montar_lotes`), cada um identificado
por post_id (= raw_picks.id) no schema de saida - o schema do documento
original (`{"palpites": [...]}`) e por-post; aqui vai um nivel
"resultados" indexado por post_id, porque um lote tem N posts na mesma
chamada. Structured outputs (`output_config.format`) garante JSON valido,
sem precisar de retry-on-parse-error nem stop_sequences.

Cache por hash de conteudo ("nunca extraia duas vezes o mesmo texto",
requisito do documento original): ja resolvido estruturalmente por
`raw_picks.hash_conteudo` (unique, Fase 0) + `raw_picks.extraido_em`
(Fase 3, migration 0010) - o script so busca raw_picks com
`extraido_em is null`, entao o mesmo texto nunca e reenviado ao modelo.
Nao precisou de tabela de cache separada.

`parse_resposta` devolve tambem o conjunto de post_ids que de fato
apareceram em "resultados": o schema JSON nao garante que o modelo
responda para todo post_id do lote, entao um post omitido pelo modelo
fica marcado como nao-processado e e reenviado no proximo run, em vez de
ser silenciosamente dado como "sem palpite" para sempre.
"""

import json
from dataclasses import dataclass

import anthropic

MODEL = "claude-haiku-4-5"
CONFIANCA_MINIMA = 0.7
MERCADOS_VALIDOS = ("1x2", "over_under", "ambas_marcam", "handicap", "escanteios", "cartoes", "outro")

SYSTEM_PROMPT = """Voce extrai dados estruturados de palpites esportivos escritos por \
tipsters brasileiros, em texto livre e informal (girias, abreviacoes, emojis).

Regras:
- Um post pode conter zero, um ou varios palpites (multiplas selecoes).
- Nunca invente um campo. Se a informacao nao estiver explicita no texto, use null.
- "confianca_extracao" (0 a 1) reflete o quanto voce tem certeza de que extraiu os \
campos corretamente daquele texto especifico - nao a confianca do tipster no palpite.
- "mercado" so pode ser um dos valores: 1x2, over_under, ambas_marcam, handicap, \
escanteios, cartoes, outro.
- Preserve o post_id exatamente como recebido, para cada post do lote, mesmo quando \
o post nao tiver nenhum palpite (nesse caso "palpites" e uma lista vazia)."""

_PALPITE_SCHEMA = {
    "type": "object",
    "properties": {
        "time_casa": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "time_fora": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "competicao": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "data_referencia": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "mercado": {"type": "string", "enum": list(MERCADOS_VALIDOS)},
        "selecao": {"type": "string"},
        "odd": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "casa_apostas": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "unidades": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "confianca_extracao": {"type": "number"},
    },
    "required": [
        "time_casa", "time_fora", "competicao", "data_referencia", "mercado",
        "selecao", "odd", "casa_apostas", "unidades", "confianca_extracao",
    ],
    "additionalProperties": False,
}

_OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "resultados": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "post_id": {"type": "string"},
                    "palpites": {"type": "array", "items": _PALPITE_SCHEMA},
                },
                "required": ["post_id", "palpites"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["resultados"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class RawPickInput:
    raw_pick_id: str
    texto_bruto: str
    autor: str | None = None


@dataclass(frozen=True)
class ExtractedPalpite:
    raw_pick_id: str
    time_casa: str | None
    time_fora: str | None
    competicao: str | None
    data_referencia: str | None
    mercado: str
    selecao: str
    odd: float | None
    casa_apostas: str | None
    unidades: float | None
    confianca_extracao: float


def montar_lotes(posts: list[RawPickInput], max_posts_por_lote: int) -> list[list[RawPickInput]]:
    return [posts[i : i + max_posts_por_lote] for i in range(0, len(posts), max_posts_por_lote)]


def montar_mensagem_usuario(lote: list[RawPickInput]) -> str:
    partes = [f'post_id: {p.raw_pick_id}\ntexto: """{p.texto_bruto}"""' for p in lote]
    return "\n\n".join(partes)


def parse_resposta(texto_json: str) -> tuple[list[ExtractedPalpite], set[str]]:
    dado = json.loads(texto_json)
    palpites: list[ExtractedPalpite] = []
    post_ids_respondidos: set[str] = set()

    for resultado in dado.get("resultados") or []:
        post_id = resultado.get("post_id")
        if not post_id:
            continue
        post_ids_respondidos.add(post_id)

        for item in resultado.get("palpites") or []:
            # Um palpite malformado dentro de um post nao pode derrubar os
            # outros do mesmo post nem os de outros posts do lote - mesma
            # licao ja aplicada em espn_summary.py e oddspapi.py.
            try:
                palpites.append(_parse_palpite(post_id, item))
            except (KeyError, TypeError, ValueError):
                continue

    return palpites, post_ids_respondidos


def _parse_palpite(post_id: str, item: dict) -> ExtractedPalpite:
    mercado = item.get("mercado")
    if mercado not in MERCADOS_VALIDOS:
        mercado = "outro"

    # confianca_extracao decide o gate extraido/revisao_manual em
    # scripts/extract_picks.py - nao confiar cegamente num valor fora de
    # [0, 1] que o modelo eventualmente devolva (o schema pede "number",
    # nao ha como forcar o intervalo direto no JSON schema).
    confianca_bruta = float(item.get("confianca_extracao") or 0.0)
    confianca = max(0.0, min(1.0, confianca_bruta))

    return ExtractedPalpite(
        raw_pick_id=post_id,
        time_casa=item.get("time_casa"),
        time_fora=item.get("time_fora"),
        competicao=item.get("competicao"),
        data_referencia=item.get("data_referencia"),
        mercado=mercado,
        selecao=item["selecao"],
        odd=item.get("odd"),
        casa_apostas=item.get("casa_apostas"),
        unidades=item.get("unidades"),
        confianca_extracao=confianca,
    )


def extrair_lote(
    client: anthropic.Anthropic, lote: list[RawPickInput]
) -> tuple[list[ExtractedPalpite], set[str], anthropic.types.Usage]:
    response = client.messages.create(
        model=MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": montar_mensagem_usuario(lote)}],
        output_config={"format": {"type": "json_schema", "schema": _OUTPUT_SCHEMA}},
    )
    texto = next(bloco.text for bloco in response.content if bloco.type == "text")
    palpites, post_ids_respondidos = parse_resposta(texto)
    return palpites, post_ids_respondidos, response.usage
