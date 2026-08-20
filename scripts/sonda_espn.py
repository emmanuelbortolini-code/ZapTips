"""Fase 1a: sonda descartavel contra a API interna da ESPN.

Nao tem teste, nao tem tratamento de erro elaborado, nao faz parte do
pipeline. O objetivo e unico: buscar scoreboard + summary de partidas reais
do Brasileirao e da Champions e salvar o JSON cru para leitura humana, para
responder com dado real (nao suposicao) as perguntas da Fase 1a do
documento de especificacao.

Uso:
    uv run python -m scripts.sonda_espn
"""

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import httpx

from app.config import get_settings

OUT_DIR = Path(
    r"C:\Users\ebort\AppData\Local\Temp\claude\C--Users-ebort-Desktop-ZapTips"
    r"\3b1bf29c-da08-44dd-9980-0a4c7b3ae669\scratchpad\sonda_espn"
)
# A borda da ESPN (provavelmente Akamai Bot Manager) bloqueia com 403
# qualquer User-Agent customizado ou que contenha "Mozilla", inclusive
# strings identificaveis como "ZapTips-Sonda/0.1". So passam UAs de
# biblioteca padrao (testado: curl/*, python-httpx/*). Documentar isso e
# decidir com o PM antes de escrever o coletor de producao — ver CLAUDE.md.
RATE_LIMIT_SECONDS = 1.0


def fetch(client: httpx.Client, url: str, label: str) -> dict:
    print(f"GET {url}")
    resp = client.get(url, timeout=15)
    resp.raise_for_status()
    data = resp.json()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{label}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    time.sleep(RATE_LIMIT_SECONDS)
    return data


def find_events(
    client: httpx.Client, base: str, liga: str, quantidade: int, datas: list[str]
) -> list[dict]:
    """Busca eventos nas datas dadas, na ordem, ate juntar `quantidade`."""
    eventos: list[dict] = []
    for yyyymmdd in datas:
        if len(eventos) >= quantidade:
            break
        url = f"{base}/{liga}/scoreboard?dates={yyyymmdd}"
        data = fetch(client, url, f"{liga}_scoreboard_{yyyymmdd}")
        novos = data.get("events", [])
        print(f"  -> {len(novos)} evento(s) em {yyyymmdd}")
        eventos.extend(novos)
    return eventos[:quantidade]


def datas_forward(dias: int) -> list[str]:
    hoje = date.today()
    return [(hoje + timedelta(days=i)).strftime("%Y%m%d") for i in range(dias)]


def main() -> int:
    settings = get_settings()
    base = settings.espn_base_url

    with httpx.Client() as client:
        print("=== Brasileirao Serie A (bra.1): procurando 3 partidas ===")
        eventos_bra = find_events(client, base, "bra.1", quantidade=3, datas=datas_forward(14))

        # Em 2026-08-09 (data do sistema) a temporada 2026-27 da Champions
        # ainda nao tem fixtures publicadas no `site.api` da ESPN (busca
        # forward em 21 dias devolveu zero eventos em todas as datas).
        # A temporada 2025-26 (a mais recente com dado real) ja terminou;
        # usamos duas datas conhecidas dela, uma de fase de liga e uma de
        # mata-mata, para ver se a estrutura do JSON muda entre fases.
        print("\n=== Champions League (uefa.champions): temporada 2026-27 sem fixtures publicadas ===")
        print("Usando datas da temporada 2025-26 (mais recente com dado real) como substituto:")
        eventos_champions = find_events(
            client, base, "uefa.champions", quantidade=2, datas=["20250916", "20260407"]
        )

        selecionados = [("bra.1", e) for e in eventos_bra] + [
            ("uefa.champions", e) for e in eventos_champions
        ]

        if not selecionados:
            print("\nNenhum evento encontrado na janela pesquisada. Amplie `dias` ou "
                  "verifique se ha jogos agendados para essas ligas no periodo.")
            return 1

        print(f"\n=== Encontrados {len(selecionados)} eventos. Buscando summary de cada um ===")
        for liga, evento in selecionados:
            event_id = evento.get("id")
            nome = evento.get("name", "?")
            print(f"\n{liga} | {event_id} | {nome}")
            if not event_id:
                print("  evento sem id, pulando summary")
                continue
            url = f"{base}/{liga}/summary?event={event_id}"
            fetch(client, url, f"{liga}_summary_{event_id}")

    print(f"\nJSON bruto salvo em: {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
