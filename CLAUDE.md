# ZapTips

Sistema de curadoria de palpites esportivos com envio assistido por WhatsApp.
Especificação completa em `prompt-claude-code-palpites.md` — este arquivo
documenta o que foi implementado e as decisões tomadas. Em caso de conflito
entre os dois, este arquivo é autoritativo; o outro é a intenção original.

Histórico detalhado (investigações, achados reais, bugs corrigidos fase a
fase) fica em [`docs/HISTORICO.md`](docs/HISTORICO.md). Aqui só o essencial
pra trabalhar no projeto hoje: stack, comandos, decisões vigentes e estado
atual de cada fase.

## Stack

- Python 3.11 (pinado via `uv`, ver `.python-version`) — `playwright`/
  `telethon` ainda não garantem suporte total ao 3.14 também instalado.
- `uv` para pacotes/venv.
- Postgres via Supabase. Migrations em SQL puro em `migrations/`, aplicadas
  por `scripts/migrate.py` (runner próprio, sem Alembic — schema evolui em
  blocos por fase, não em incrementos finos de ORM).
- `httpx`, `tenacity`, `pydantic`/`pydantic-settings`, `psycopg[binary]` v3,
  `structlog`, `rapidfuzz`, `beautifulsoup4`, `anthropic`, `jinja2`,
  `fastapi`+`uvicorn`+`python-multipart` (console local), `apscheduler`
  (agendador).

## Estrutura

```
app/            pacote principal (config, domínio, console FastAPI em app/console/)
migrations/     .sql numerados, aplicados em ordem por scripts/migrate.py
scripts/        CLIs (migrate, coletores, extract_picks, link_picks,
                resolve_odds, build_slate, run_pipeline, users, subs,
                console, liquidacao, relatorio, agendador, backup, health)
tests/          pytest
docs/           HISTORICO.md (registro fase a fase completo)
```

## Comandos

`make` não vem por padrão neste Windows — os alvos do `Makefile` são atalho
pros comandos `uv run` abaixo; use-os direto se não tiver `make` (Git Bash
com MSYS2/coreutils ou WSL têm).

| Objetivo | Comando |
|---|---|
| Instalar dependências | `uv sync --dev` |
| Aplicar migrations pendentes | `uv run python -m scripts.migrate` |
| Rodar testes | `uv run pytest` |
| Sondas/coleta (ESPN, OddsPapi, fixtures, resultados, odds, Eagle Predict, SDA) | `uv run python -m scripts.sonda_espn` / `sonda_oddspapi` / `collect_fixtures` / `collect_results` / `collect_odds` / `collect_eagle_predict` / `collect_sda` (`--backfill` p/ SDA, uma vez só) |
| Seed de team_aliases | `uv run python -m scripts.seed_team_aliases` |
| Extração/matching/odds/slate | `uv run python -m scripts.extract_picks` / `link_picks` / `resolve_odds` / `build_slate` |
| Pipeline diário completo (com resume) | `uv run python -m scripts.run_pipeline` (`--forcar-etapa <nome>` p/ forçar) |
| Assinantes/assinaturas | `uv run python -m scripts.users cadastrar\|optin\|optout\|export ...` / `scripts.subs registrar\|vencendo ...` |
| Console local | `uv run python -m scripts.console` → `http://127.0.0.1:8000` |
| Liquidação / revisão manual | `uv run python -m scripts.liquidar_picks` / `scripts.liquidacao listar\|marcar` |
| Extrato mestre / apostas por usuário | `uv run python -m scripts.build_master_ledger` / `scripts.build_bets` |
| Relatórios (usuário, fontes, diário) | `uv run python -m scripts.relatorio usuario\|fontes\|diario ...` |
| Mensagens de fechamento / resumo semanal | `uv run python -m scripts.gerar_fechamentos` / `scripts.gerar_resumo_semanal` |
| Página pública de performance (gera `public/index.html`+`resumo.txt`) | `uv run python -m scripts.gerar_pagina_publica` |
| Agendador (processo único, produção) | `uv run python -m scripts.agendador` |
| Backup do Postgres | `uv run python -m scripts.backup` |
| Health check (mesmos dados da aba /saude) | `uv run python -m scripts.health` |

Alvos `make` equivalentes existem pros comandos sem argumento obrigatório
(ver `Makefile`); comandos com args obrigatórios (`cadastrar`, `registrar`,
`export`, `marcar`, backfill do SDA) só têm a forma `uv run`.

## Variáveis de ambiente

Ver `.env.example` para a lista completa comentada. Parâmetros de negócio:

| Variável | Valor | Motivo |
|---|---|---|
| `ODD_MINIMA_ABSOLUTA` | `1.40` | Piso alinhado ao range real do SDA (1.44–2.45) |
| `MARGEM_PCT` | `0.04` | Default do documento original |
| `SLATE_MAX_PICKS` | `5` | Curadoria rápida, mensagem enxuta |
| `BANCA_INICIAL_PADRAO` | `1000` | — |
| `STAKE_PCT_PADRAO` | `0.02` | Conservador p/ sequência longa de reds em odds baixas |
| `STAKE_MODO_PADRAO` | `fixo` | Isola qualidade do palpite do dimensionamento (ROI comparável por fonte) |
| `MAX_ASSINANTES_ATIVOS` | `50` | Trava de código |
| `DIVERGENCIA_ODD_ALERTA_PCT` | `0.10` | Alerta visual (nunca bloqueio) na curadoria |

`DATABASE_URL` aponta pro Supabase real; senha com caracteres especiais
precisa de URL-encoding. `.env` não é versionado.

## Ambiente de execução

Roda só na máquina local do PM, sem servidor. Console sem autenticação,
scheduler via APScheduler em processo único (`scripts/agendador.py`).

## Decisões de negócio vigentes

- Captação de assinantes do zero (sem base prévia); sem afiliado, sem trial,
  teto de 50 assinantes; ESPN como fonte única de partidas.
- Stake fixo sobre banca inicial (não proporcional); banca inicial 1000,
  stake 2%; slate de 3–5 palpites/dia; `ODD_MINIMA_ABSOLUTA` 1.40.
- User-Agent do coletor ESPN: default do `httpx` (qualquer UA identificável
  ou com "Mozilla" leva a 403).
- Hierarquia de odds: 1) fonte cita casa licenciada → 2) OddsPapi (bet365/
  betano/superbet — `1x2`, `ambas_marcam` e `over_under`, ampliado em
  2026-08-20; mesmo payload de `/odds-by-tournaments` já buscado, sem
  custo extra de cota) → 3) bloco nativo da ESPN (`app/espn_odds.py`,
  só mercado 1x2, odds americanas convertidas pra decimal — casa licenciada
  raramente aparece no bloco hoje, ver Estado do projeto) → 4) manual via console.
- **Não haverá créditos de API da Anthropic** (decisão permanente,
  2026-08-13, restrição de orçamento). `scripts/extract_picks.py` continua
  correto mas não roda contra a API real — a etapa `extracao` do pipeline
  fecha `degradado` por design. Extração de `raw_picks` pendentes é feita
  sob demanda via subagentes do Claude Code (coberto pela assinatura Pro),
  reaproveitando `app/extraction.py`/`scripts/extract_picks.py` como
  caminho de escrita único. Rodar quando o PM pedir ("extrai os picks
  pendentes"), não automaticamente.

## Marco: primeira mensagem real enviada via WhatsApp

Em 2026-08-20, o ciclo completo do produto rodou de ponta a ponta pela
primeira vez com dado real: pipeline → extração assistida → vínculo →
odd (palpite manual com odd verificada ao vivo contra o mercado,
mercados automáticos ainda sem dado pra fixtures futuras) → curadoria →
aprovação → geração de mensagem → fila de envio → **enviada de verdade
pelo WhatsApp** pro assinante real. Confirmado no Postgres
(`messages.status = 'enviada'`). Detalhe completo, incluindo o que
não funcionou automaticamente e por quê, em
[`docs/HISTORICO.md`](docs/HISTORICO.md).

## Estado do projeto (fases)

Fase 0 (fundação/schema) até Fase 7 (operação/scheduler) estão com o
**escopo central concluído e validado contra o Postgres real**. Resumo por
fase — detalhe completo em [`docs/HISTORICO.md`](docs/HISTORICO.md):

- **Fase 0** — Schema inicial (`migrations/0001_init.sql`).
- **Fase 1 (a–g)** — Sonda ESPN + OddsPapi, matcher de times
  (`app/matcher.py`), seed de `team_aliases`, coletores de fixtures/
  resultados/odds. 42 fixtures e 84 odds de referência coletadas.
- **Fase 2** — Coletores Eagle Predict e SDA (Telegram/WordPress scraping),
  ambos em quarentena por padrão. ~770 `raw_picks` coletados no backfill.
- **Fase 3** — Extração estruturada de picks (schema + prompt validados
  20/20 numa amostra manual; ~1076 picks extraídos ao todo até agora). Ver
  decisão sobre créditos de API acima.
- **Fase 4** — Vínculo pick↔fixture, resolução de odds/piso (níveis 1–3
  da hierarquia, incluindo `app/espn_odds.py`), motor de montagem do
  slate, template de mensagem.
- **Fase 5 (a–d)** — Orquestrador de pipeline com resume, CLI de
  assinantes/opt-in/opt-out (LGPD), console FastAPI (`/saude`,
  `/curadoria`, `/envio` com modo manual e modo sessão guiada). Design
  visual (2026-08-20): tema "console de operações" dark, tokens CSS em
  `app/console/static/console.css`, badges de status, dashboard em
  cards — todos os 9 templates redesenhados sem tocar em lógica/forms;
  `sessao.js` (Fase 5d-D) continua funcionando, seletores preservados.
  `/saude` ganhou botão "sincronizar" por etapa (`POST /saude/
  sincronizar/{etapa}`, roda em background via `BackgroundTasks`, com
  trava em memória contra clique duplo — detalhe em `docs/HISTORICO.md`).
  `/curadoria` ganhou a seção "Todos os palpites do dia" (todo pick
  ligado a fixture nas próximas 24h, qualquer status — não só os que
  entraram no slate). `/envio` ganhou edição de texto por mensagem
  (`POST /envio/{id}/editar`, só enquanto `status='pronta'`, reaproveita
  `regerar_corpos` que já existia sem uso).
- **Fase 6 (a–e)** — Motor de liquidação por mercado (1x2, ambas marcam,
  over/under, handicap, escanteios, cartões), simulação de banca
  (`master_ledger`/`bets`), métricas por usuário, performance por fonte,
  mensagens de fechamento de palpite e resumo semanal.
- **Fase 7** — Agendador único (`scripts/agendador.py`), health check,
  relatório diário, backup do Postgres, e página pública de performance
  (`scripts/gerar_pagina_publica.py`, HTML+texto estáticos gerados em
  `public/`, regenerados no fechamento diário — publicar/hospedar
  continua manual, o script só gera o arquivo).

## Pendências conhecidas

1. Publicar/hospedar `public/index.html` (Netlify Drop, GitHub Pages etc.)
   continua manual — o script só gera o artefato local, nunca sobe sozinho.
2. ~~`pg_dump` não instalado~~ — resolvido em 2026-08-20: PostgreSQL 17
   client tools instalado via `winget` (`PostgreSQL.PostgreSQL.17`), bin
   adicionado ao PATH do usuário. O instalador do winget sobe o serviço
   completo do Postgres junto (não só o cliente) — parar/desabilitar o
   serviço `postgresql-x64-17` exige admin, que esta sessão não tem;
   segue rodando (porta padrão 5432, não usado pelo projeto — o banco
   real é o Supabase). `scripts/backup.py` validado contra o Postgres
   real, dump gravado em `backups/`. Ação pendente pro PM: desativar o
   serviço manualmente se quiser liberar a porta/RAM (Serviços do
   Windows → `postgresql-x64-17` → parar + desabilitar).
3. Detecção de conflito em `app/slate.py` só normaliza seleção pro mercado
   1x2; `over_under`/`ambas_marcam`/`handicap` comparam texto bruto.
4. Parser de "cartões, condição por time" — só o marcador existe, falta
   texto real pra validar o parser completo.
5. Alerta de 15% de picks não-liquidáveis por fonte — não existe canal de
   alerta no projeto ainda.
6. `casas.aliases` vazio (sem urgência — resolução de `casa_id` já é 100%
   sem alias; `app/espn_odds.py` contorna isso normalizando nome, não
   dependendo de alias).
7. ~~Contagem de revisão manual não aparece em `/saude`~~ — resolvido em
   2026-08-20 (`revisao_manual_pendente`, painel no dashboard e no CLI
   `health`).
8. `scripts/relatorio.py` (usuário/fontes) só tem CLI — nenhuma rota do
   console mostra essas métricas ainda.
9. Uso auxiliar do `/settlements` do OddsPapi (conferência amostral de
   liquidação) — não implementado.
10. Agendador nunca rodou um dia inteiro em produção — só validado
    localmente (start/stop, registro dos jobs).
11. ~~Matcher recusava "Grêmio Novorizontino SP"~~ — resolvido em
    2026-08-20: `app.matcher.match_team_name` agora prioriza um match
    exato de UM time sobre empate com fuzzy de OUTRO time (antes os dois
    empatavam no teto de score e sempre iam pra `revisao_manual`, mesmo
    com um match exato em mãos). Dois times com alias exato idêntico
    continuam corretamente ambíguos (América-MG/RN, não regrediu).
    `migrations/0028` adiciona o alias que faltava.
12. Família "América-MG/América-RN" (dois times distintos que colidem
    depois de normalizar) continua sem resolução automática, por
    design — inclui agora um caso real confirmado: "Novorizontino x
    América Mineiro" não resolve odd porque "América Mineiro" cai
    nessa mesma família. Só resolve com alias manual específico, caso a
    caso, como fiz pro Novorizontino/Grêmio.
13. Volume real ainda baixo pra validar conflito de picks/limite diário do
    slate com dado de produção de verdade.
14. ~~`app/oddspapi.py::_parse_fixture` só reconhece mercado 1x2 sob uma
    chave fixa~~ — investigação de 2026-08-20 estava **errada**: a
    chave `"101"` estava presente nas duas fixtures de Série B
    testadas, com preços reais, mas `marketActive: false` (bet365 **e**
    betano, mesmas duas partidas) — mercado temporariamente suspenso,
    não indisponível por falha de parsing. O parser recusa corretamente
    (usar preço de mercado inativo violaria "piso publicado é sempre
    apostável de verdade"). Não é bug, não precisa de correção. Hipótese
    não testada: o mercado pode ativar mais perto do kickoff — revisitar
    rodando `collect_odds.py` de novo poucas horas antes de uma partida
    de Série B pra confirmar.

Para o "porquê" de qualquer decisão acima, ou o relato completo de uma
investigação (sondas, bugs de revisão de código, achados por fase), ver
[`docs/HISTORICO.md`](docs/HISTORICO.md).
