.PHONY: setup migrate test sonda-espn sonda-oddspapi seed-team-aliases collect-fixtures collect-results collect-odds collect-eagle-predict collect-sda extract-picks link-picks resolve-odds build-slate run-pipeline subs-vencendo console generate-messages

# Requer `make` (Git Bash com MSYS2/coreutils, WSL, ou Linux/macOS).
# No Windows sem `make` instalado, rode os comandos `uv run ...` direto
# (ver CLAUDE.md, secao "Comandos").

setup:
	uv sync --dev
	uv run python -m scripts.migrate

migrate:
	uv run python -m scripts.migrate

test:
	uv run pytest

sonda-espn:
	uv run python -m scripts.sonda_espn

sonda-oddspapi:
	uv run python -m scripts.sonda_oddspapi

seed-team-aliases:
	uv run python -m scripts.seed_team_aliases

collect-fixtures:
	uv run python -m scripts.collect_fixtures

collect-results:
	uv run python -m scripts.collect_results

collect-odds:
	uv run python -m scripts.collect_odds

collect-eagle-predict:
	uv run python -m scripts.collect_eagle_predict

collect-sda:
	uv run python -m scripts.collect_sda

extract-picks:
	uv run python -m scripts.extract_picks

link-picks:
	uv run python -m scripts.link_picks

resolve-odds:
	uv run python -m scripts.resolve_odds

build-slate:
	uv run python -m scripts.build_slate

run-pipeline:
	uv run python -m scripts.run_pipeline

subs-vencendo:
	uv run python -m scripts.subs vencendo

console:
	uv run python -m scripts.console

generate-messages:
	uv run python -m scripts.generate_messages
