"""Verificacao antes de implementar o adapter do OddsPapi (Fase 1).

Descartavel, sem teste, sem tratamento de erro elaborado. Chama
/bookmakers, /tournaments e uma vez /odds-by-tournaments com dado real
para responder as 5 perguntas da secao "Verificacao antes de implementar"
do documento de especificacao, com base em retorno real, nao suposicao.
Cada chamada conta contra a cota mensal de 250 requisicoes — rodar so
quando necessario, nunca em loop.

Uso:
    uv run python -m scripts.sonda_oddspapi
"""

import json
import sys
import time
from pathlib import Path

import httpx

from app.config import get_settings

OUT_DIR = Path(
    r"C:\Users\ebort\AppData\Local\Temp\claude\C--Users-ebort-Desktop-ZapTips"
    r"\4cdc08c2-bf55-4375-b4fd-0fc0b223d9f3\scratchpad\sonda_oddspapi"
)
COOLDOWN_SECONDS = 5.0
CASAS_BRASILEIRAS_ESPERADAS = ["superbet", "bet365", "betano", "novibet", "betboom", "vbet"]


def fetch(client: httpx.Client, path: str, label: str, params: dict) -> dict:
    url = f"{path}"
    print(f"GET {url} params={params}")
    resp = client.get(url, params=params, timeout=20)
    resp.raise_for_status()
    data = resp.json()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / f"{label}.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    time.sleep(COOLDOWN_SECONDS)
    return data


def main() -> int:
    settings = get_settings()
    if not settings.oddspapi_api_key:
        print("ODDSPAPI_API_KEY vazia no .env, abortando.")
        return 1

    base = settings.oddspapi_base_url
    requisicoes = 0

    with httpx.Client(base_url=base) as client:
        params_comuns = {"apiKey": settings.oddspapi_api_key, "oddsFormat": "decimal"}

        print("=== 1. /bookmakers: casas disponiveis ===")
        bookmakers = fetch(client, "/bookmakers", "bookmakers", params_comuns)
        requisicoes += 1
        lista_bookmakers = bookmakers if isinstance(bookmakers, list) else bookmakers.get("data", bookmakers)
        print(f"Total de casas retornadas: {len(lista_bookmakers) if hasattr(lista_bookmakers, '__len__') else '?'}")

        print("\n=== 2. /tournaments: procurando Brasileirao Serie A e B ===")
        tournaments = fetch(client, "/tournaments", "tournaments", params_comuns)
        requisicoes += 1
        lista_tournaments = tournaments if isinstance(tournaments, list) else tournaments.get("data", tournaments)

        candidatos_brasileirao = []
        if hasattr(lista_tournaments, "__iter__") and not isinstance(lista_tournaments, dict):
            for t in lista_tournaments:
                nome = json.dumps(t, ensure_ascii=False).lower()
                if "brasil" in nome or "brazil" in nome or "brasileir" in nome:
                    candidatos_brasileirao.append(t)
        print(f"Torneios com 'brasil'/'brazil' no payload: {len(candidatos_brasileirao)}")
        for t in candidatos_brasileirao[:15]:
            print(f"  {t}")

        tournament_ids = [
            t.get("tournamentId") or t.get("id")
            for t in candidatos_brasileirao
            if t.get("tournamentId") or t.get("id")
        ]

        if tournament_ids:
            bookmaker_teste = "bet365"
            print(f"\n=== 3. /odds-by-tournaments com bookmaker={bookmaker_teste}, tournamentIds={tournament_ids} ===")
            params_odds = {
                **params_comuns,
                "bookmaker": bookmaker_teste,
                "tournamentIds": ",".join(str(i) for i in tournament_ids),
            }
            odds = fetch(client, "/odds-by-tournaments", "odds_by_tournaments_bra", params_odds)
            requisicoes += 1
            lista_odds = odds if isinstance(odds, list) else odds.get("data", odds)
            print(f"Partidas retornadas: {len(lista_odds) if hasattr(lista_odds, '__len__') else '?'}")
        else:
            print("\nNenhum tournamentId de Brasileirao encontrado, pulando /odds-by-tournaments.")

    print(f"\nJSON bruto salvo em: {OUT_DIR}")
    print(f"Requisicoes consumidas nesta execucao: {requisicoes}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
