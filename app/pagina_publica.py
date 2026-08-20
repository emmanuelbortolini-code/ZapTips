"""Renderizacao da pagina publica de performance (Fase 7, spec "Pagina
publica de performance") - dois artefatos, os dois funcoes puras sobre
`app.relatorio_publico.DadosPublicos`:

1. `renderizar_html_publico`: pagina HTML de arquivo unico (CSS e SVG
   inline, sem JS, sem CDN, sem chamada de rede nenhuma) - "eu posso
   hospedar em qualquer lugar ou mandar por link" (spec). O grafico da
   curva de banca e' um `<svg><polyline>` calculado em Python, espacado
   por INDICE (nao por tempo real) - decisao desta sessao: a cadencia de
   picks publicados nao e' uniforme (dias sem pick nenhum), e um eixo
   por indice mostra a FORMA da curva sem "buracos" longos e vazios que
   um eixo temporal estrito produziria com o volume atual (poucas
   dezenas de pontos). Revisitar se o volume crescer o suficiente pra um
   eixo temporal real valer a pena.
2. `renderizar_texto_publico`: resumo em texto pronto pra colar no
   WhatsApp (spec, item 2).

Regras de apresentacao da spec, obrigatorias no codigo e NAO
configuraveis, aplicadas nos dois artefatos:
- "simulada" acompanha toda mencao a banca
- Frase fixa de metodologia (banca inicial, stake, piso publicado -
  nunca a odd real obtida pelo assinante)
- Nenhum texto de projecao/previsao/expectativa de retorno futuro
- Todo numero vem com o periodo que cobre (por isso os 3 `PeriodoPublico`
  sao sempre exibidos com o nome do periodo ao lado)
- Aviso 18+ e jogo responsavel no rodape (mesmo `rodape_legal` de
  app.config, ja usado em toda mensagem enviada - Fase 4)
- Extrato MESTRE completo, nunca de um assinante - `DadosPublicos` so'
  carrega numeros agregados, nenhum `user_id`/telefone/nome chega aqui
"""

from decimal import Decimal

from jinja2 import Environment, StrictUndefined
from markupsafe import Markup

from app.relatorio_publico import DadosPublicos
from app.settlement.metricas_publicas import PeriodoPublico

_FRASE_METODOLOGIA = (
    "Metodologia: banca simulada inicial de R$ {banca_inicial}, stake de {stake_pct} por aposta. "
    "O calculo assume que a aposta foi feita no PISO publicado no momento do envio, "
    "nunca na odd real eventualmente obtida por quem apostou - o piso e sempre o cenario mais conservador."
)

_env = Environment(autoescape=True, undefined=StrictUndefined, trim_blocks=True, lstrip_blocks=True)

_TEMPLATE_HTML = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>ZapTips - Performance</title>
<style>
  body { font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }
  h1 { font-size: 1.4rem; }
  .periodo { border: 1px solid #ddd; border-radius: 8px; padding: 1rem; margin: 1rem 0; }
  .periodo h2 { font-size: 1.1rem; margin: 0 0 .5rem; }
  .metrica { display: flex; justify-content: space-between; padding: .15rem 0; }
  .nao-liquidados { color: #a55b00; }
  .metodologia { font-size: .85rem; color: #444; background: #f6f6f6; padding: .75rem 1rem; border-radius: 8px; }
  .rodape { font-size: .8rem; color: #666; white-space: pre-line; margin-top: 2rem; }
  .atualizado { font-size: .8rem; color: #666; }
  svg { width: 100%; height: auto; border: 1px solid #ddd; border-radius: 8px; }
</style>
</head>
<body>
<h1>ZapTips — Performance do extrato mestre (banca simulada)</h1>
<p class="atualizado">Ultima atualizacao: {{ gerado_em }}</p>

<p class="metodologia">{{ frase_metodologia }}</p>

<h2>Curva da banca simulada desde o inicio da operacao</h2>
{{ svg_curva }}

{% for periodo in periodos %}
<div class="periodo">
  <h2>{{ periodo.nome }}</h2>
  <div class="metrica"><span>Banca simulada</span><span>R$ {{ periodo.banca_texto }}</span></div>
  <div class="metrica"><span>ROI ({{ periodo.nome }})</span><span>{{ periodo.roi_texto }}</span></div>
  <div class="metrica nao-liquidados"><span>Nao liquidados ({{ periodo.nome }})</span><span>{{ periodo.metricas.nao_liquidados_no_periodo }}</span></div>
  <div class="metrica"><span>Volume ({{ periodo.nome }})</span><span>{{ periodo.metricas.apostas_no_periodo }}</span></div>
  <div class="metrica"><span>Taxa de acerto ({{ periodo.nome }})</span><span>{{ periodo.taxa_acerto_texto }}</span></div>
  <div class="metrica"><span>Odd media ({{ periodo.nome }})</span><span>{{ periodo.odd_media_texto }}</span></div>
</div>
{% endfor %}

<p class="rodape">{{ rodape_legal }}</p>
</body>
</html>"""

_template_html = _env.from_string(_TEMPLATE_HTML)


def _formatar_roi(roi: Decimal | None) -> str:
    return f"{roi:.2%}" if roi is not None else "sem apostas no periodo"


def _formatar_taxa_acerto(taxa: Decimal | None) -> str:
    return f"{taxa:.1%}" if taxa is not None else "sem apostas decididas no periodo"


def _formatar_odd_media(odd: Decimal | None) -> str:
    return f"{odd:.2f}" if odd is not None else "-"


def _montar_svg_curva(curva: tuple[tuple, ...], banca_inicial: Decimal) -> str:
    valores = [float(banca) for _kickoff, banca in curva]
    if len(valores) < 2:
        # Curva de 1 ponto so' (nenhuma aposta ainda) - nada pra tracar,
        # mas a pagina nao pode quebrar por falta de historico.
        return '<svg viewBox="0 0 800 200"><text x="400" y="100" text-anchor="middle">Sem apostas liquidadas ainda</text></svg>'

    minimo, maximo = min(valores), max(valores)
    amplitude = maximo - minimo or 1.0
    largura, altura, margem = 800, 200, 10
    passo_x = (largura - 2 * margem) / (len(valores) - 1)

    def _y(v: float) -> float:
        # Inverte o eixo Y (SVG cresce pra baixo) - banca maior fica mais
        # acima na imagem, leitura intuitiva de grafico de linha.
        return margem + (altura - 2 * margem) * (1 - (v - minimo) / amplitude)

    pontos = " ".join(f"{margem + i * passo_x:.1f},{_y(v):.1f}" for i, v in enumerate(valores))
    return (
        f'<svg viewBox="0 0 {largura} {altura}" preserveAspectRatio="none">'
        f'<polyline points="{pontos}" fill="none" stroke="#1a7f37" stroke-width="2" />'
        f"</svg>"
    )


class _PeriodoParaTemplate:
    def __init__(self, periodo: PeriodoPublico):
        self.nome = periodo.nome
        self.metricas = periodo.metricas
        self.banca_texto = f"{periodo.metricas.banca_atual:.2f}"
        self.roi_texto = _formatar_roi(periodo.metricas.roi)
        self.taxa_acerto_texto = _formatar_taxa_acerto(periodo.metricas.taxa_acerto)
        self.odd_media_texto = _formatar_odd_media(periodo.metricas.odd_media)


def _frase_metodologia(dados: DadosPublicos, stake_pct: Decimal) -> str:
    return _FRASE_METODOLOGIA.format(banca_inicial=f"{dados.banca_inicial:.2f}", stake_pct=f"{stake_pct:.1%}")


def renderizar_html_publico(dados: DadosPublicos, rodape_legal: str, stake_pct: Decimal) -> str:
    if not rodape_legal or not rodape_legal.strip():
        raise ValueError("rodape_legal e obrigatorio - nunca opcional (documento original, secao Template)")

    return _template_html.render(
        gerado_em=dados.gerado_em.strftime("%d/%m/%Y %H:%M UTC"),
        frase_metodologia=_frase_metodologia(dados, stake_pct),
        # Markup: SVG e' gerado por _montar_svg_curva a partir so' de
        # numeros (Decimal/float ja calculados, nenhum texto vindo de
        # pick/tipster/fonte) - o autoescape=True do ambiente e' pra
        # proteger contra dado nao confiavel, que nao existe aqui; sem
        # Markup, o autoescape escaparia as tags do proprio SVG que
        # geramos e a pagina mostraria a marcacao crua em vez do grafico.
        svg_curva=Markup(_montar_svg_curva(dados.curva_banca, dados.banca_inicial)),
        periodos=[_PeriodoParaTemplate(p) for p in dados.periodos],
        rodape_legal=rodape_legal,
    )


_TEMPLATE_TEXTO = """ZapTips - Performance (banca simulada)

{frase_metodologia}

{blocos_periodo}
{rodape_legal}"""


def renderizar_texto_publico(dados: DadosPublicos, rodape_legal: str, stake_pct: Decimal) -> str:
    if not rodape_legal or not rodape_legal.strip():
        raise ValueError("rodape_legal e obrigatorio - nunca opcional (documento original, secao Template)")

    frase = _frase_metodologia(dados, stake_pct)
    blocos = []
    for periodo in dados.periodos:
        m = periodo.metricas
        blocos.append(
            f"{periodo.nome}:\n"
            f"  Banca simulada: R$ {m.banca_atual:.2f}\n"
            f"  ROI ({periodo.nome}): {_formatar_roi(m.roi)}\n"
            f"  Nao liquidados ({periodo.nome}): {m.nao_liquidados_no_periodo}\n"
            f"  Volume ({periodo.nome}): {m.apostas_no_periodo}\n"
            f"  Taxa de acerto ({periodo.nome}): {_formatar_taxa_acerto(m.taxa_acerto)}\n"
            f"  Odd media ({periodo.nome}): {_formatar_odd_media(m.odd_media)}"
        )

    return _TEMPLATE_TEXTO.format(
        frase_metodologia=frase, blocos_periodo="\n\n".join(blocos), rodape_legal=rodape_legal,
    ) + f"\n\nUltima atualizacao: {dados.gerado_em.strftime('%d/%m/%Y %H:%M UTC')}"
