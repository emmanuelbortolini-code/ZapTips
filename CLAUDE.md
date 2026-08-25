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
| Sondas/coleta (ESPN, OddsPapi, fixtures, resultados, odds, Eagle Predict, SDA, APWin) | `uv run python -m scripts.sonda_espn` / `sonda_oddspapi` / `collect_fixtures` / `collect_results` / `collect_odds` / `collect_eagle_predict` / `collect_sda` (`--backfill` p/ SDA, uma vez só) / `collect_apwin` |
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
| `NAO_LIQUIDAVEL_ALERTA_PCT` | `0.15` | Alerta em `/saude`/`scripts/health.py` quando uma fonte passa desse % de não-liquidados |

`DATABASE_URL` aponta pro Supabase real; senha com caracteres especiais
precisa de URL-encoding. `.env` não é versionado.

## Ambiente de execução

Console roda só na máquina local do PM, sem servidor, sem autenticação —
isso não mudou. O **scheduler** deixou de depender do PC do PM ficar ligado
(2026-08-20): os 5 jobs recorrentes (pipeline diário, coleta+liquidação a
cada 30min, fechamento diário, backup, resumo semanal) rodam via GitHub
Actions cron (`.github/workflows/*.yml`), usando os secrets `DATABASE_URL`
e `ODDSPAPI_API_KEY` do repositório. `scripts/agendador.py` (APScheduler,
processo único) continua existindo e funcional pra rodar local/manual, mas
não é mais o caminho de produção.

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
  **APWin Decreasing Stats** (Fonte 4 do documento original) construída
  em 2026-08-25 (`app/apwin.py` + `scripts/collect_apwin.py`) — mercado
  vem da URL da página, não do texto, então pula
  `scripts/extract_picks.py` de propósito: grava `raw_picks` e `picks`
  estruturado na mesma transação, marcando `extraido_em` na hora.
  Primeira fonte a popular `picks.stat_fonte`/`stat_fonte_tipo`
  (`'frequencia_ultimos_jogos'`) — nunca `confianca_tipster`, que é só
  pra confiança declarada. Escopo desta entrega: só as 4 páginas cujo
  mercado já é totalmente suportado por `app/settlement/engine.py`
  (`ambas_marcam`, `over_under` 2.5 gols, `escanteios` 9.5,
  `cartoes` 4.5 — jogo inteiro, nunca "por time"/1º tempo), e só
  Brasileirão A/B (`bra.1`/`bra.2`, as únicas ligas com
  `league_map.oddspapi_tournament_id` mapeado hoje) — decisão do PM
  pra nunca coletar palpite sem chance real de odd/liquidação. Resolve
  fixture/time no próprio coletor (não passa por `link_picks.py`),
  descartando a entrada (nunca `revisao_manual`) quando o time ou a
  fixture não resolvem com confiança. Validado contra o site e o
  Postgres reais: fonte criada com `quarentena=true`, 4 picks reais
  vinculados a fixtures de Série B, confirmado que nenhum passa no
  filtro `s.quarentena is not true` (curadoria/slate). Ficam de fora,
  documentado como próximo passo: páginas "por time"
  (`team-over-25-cards`, `team-scored-in-both-halves`,
  `team-over-goals`) e `over-ht-goals` (mercado de 1º tempo, não existe
  em `MERCADOS_VALIDOS`) — as páginas "por time" são a mesma categoria
  da pendência 4 do histórico ("cartões condição por time") e dariam o
  primeiro dado real estruturado desse tipo, mas não foram construídas
  nesta entrega. Grupo de comparação abaixo de 100% (pro relatório de
  decisão de 60 dias da quarentena) também fica de fora — a página não
  tem parâmetro de URL simples pra isso.
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

1. ~~Publicar/hospedar `public/index.html` continua manual~~ — resolvido em
   2026-08-25: repo tornado público (era privado, GitHub Pages grátis exige
   isso) e `.github/workflows/fechamento-diario.yml` ganhou um job
   `publicar` (`actions/upload-pages-artifact` + `actions/deploy-pages`)
   que sobe `public/index.html` pro GitHub Pages sempre que o arquivo é
   gerado. Validado com execução manual real: todos os passos verdes,
   página no ar em `https://emmanuelbortolini-code.github.io/ZapTips/`
   com conteúdo real (não é mais só o artefato local).
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
3. ~~Detecção de conflito em `app/slate.py` só normaliza seleção pro
   mercado 1x2~~ — resolvido em 2026-08-25: `chave_selecao` agora também
   usa `normalizar_selecao_over_under` (direção+linha, parseada do texto
   da própria seleção) e `normalizar_selecao_ambas_marcam`, ambos já
   existentes em `app/odds_resolution.py` e usados na resolução de odds,
   só não estavam plugados no agrupamento de conflito. `handicap`
   continua comparando texto bruto por design — não existe normalizador
   pra esse mercado em lugar nenhum do projeto (a resolução de odds pra
   handicap também é só manual hoje), então não havia base pra construir
   um aqui especulativamente.
4. Parser de "cartões, condição por time" — só o marcador existe, falta
   texto real pra validar o parser completo. Reverificado em 2026-08-25:
   `raw_picks` inteiro (todo texto bruto já coletado, extraído ou não)
   tem só 1 menção a "cart..." na história do projeto, e é mercado
   `total` (over/under), não condição-por-time — segue sem exemplo real
   pra validar contra. Continua bloqueada até a fonte APWin (única citada
   com esse mercado) existir, ou aparecer texto real em outra fonte.
5. ~~Alerta de 15% de picks não-liquidáveis por fonte~~ — resolvido em
   2026-08-25: `app.settlement.performance_fonte.alertas_nao_liquidados`
   (função pura, mesma cautela de `sugerir_acoes` — `volume_minimo=10`
   evita alertar sobre uma fonte nova com amostra pequena) mais
   `app.console.queries.fontes_alerta_nao_liquidados` (reaproveita
   `gerar_relatorio_por_fonte`, mesma consulta de `scripts/relatorio.py
   fontes`). Canal escolhido: mesmo painel de `/saude` e
   `scripts/health.py` já usado pra `revisao_manual_pendente` — o
   projeto não tem (nem precisa de) canal externo (e-mail/Slack), é
   ferramenta de operador solo. Limiar configurável via
   `NAO_LIQUIDAVEL_ALERTA_PCT` (default `0.15`, mesmo padrão de
   `DIVERGENCIA_ODD_ALERTA_PCT`). Validado contra o Postgres real via
   `uv run python -m scripts.health`.
6. `casas.aliases` vazio (sem urgência — resolução de `casa_id` já é 100%
   sem alias; `app/espn_odds.py` contorna isso normalizando nome, não
   dependendo de alias). Reverificado em 2026-08-25 contra o Postgres
   real: 1172/1182 picks (99,15%) têm `casa_id` resolvido; dos 10 sem
   match, nenhum é caso de nome grafado diferente que um alias
   resolveria — todos citam casa não-licenciada (`1XBET`) ou são picks
   manuais sem casa citada. Não há dado real que justifique popular
   aliases hoje.
7. ~~Contagem de revisão manual não aparece em `/saude`~~ — resolvido em
   2026-08-20 (`revisao_manual_pendente`, painel no dashboard e no CLI
   `health`).
8. ~~`scripts/relatorio.py` (usuário/fontes) só tem CLI~~ — parcialmente
   resolvido em 2026-08-25: nova aba **Relatórios** no console
   (`app/console/rotas_relatorios.py` + `templates/relatorios.html`)
   mostra performance por fonte dos últimos 30 dias, reaproveitando
   `carregar_relatorio_fontes_30d` (que já existia em `queries.py`, mas
   nunca era chamado — código morto até agora). Validado contra o
   Postgres real (`uv run python -m scripts.console`, dado de produção
   apareceu certo, ROI sempre junto da taxa de acerto). Detalhe por
   mercado/tipster, sugestões de desativação/promoção e o relatório por
   **usuário** (exige `--user-id`, sem seletor de assinante na UI) ficam
   de fora por decisão desta sessão — continuam só CLI.
9. Uso auxiliar do `/settlements` do OddsPapi (conferência amostral de
   liquidação) — parcialmente resolvido em 2026-08-25:
   `app.oddspapi.fetch_settlements` existe e foi validado com chamada
   real (consumiu 2 de cota) contra uma fixture bra.1 futura. Schema
   real confirmado: `{"fixtureId": ..., "markets": {"101": {"outcomes":
   {"101/102/103": {"players": {"0": {"result": "UNDECIDED"}}}}}}}` -
   mercado/outcomes batem com `MARKET_1X2_ID`/`OUTCOME_1X2` já usados.
   **Bloqueado além disso**: não existe hoje nenhuma fixture DECIDIDA
   acessível (`fixtures.oddspapi_fixture_id` nunca foi persistido pelo
   projeto; `/odds-by-tournaments` só devolve partidas futuras) pra
   descobrir o vocabulário real de `result` quando o mercado fecha
   (WON/LOST/algo mais - não documentado). Escrever esse parser e ligar
   no fluxo de `liquidar_picks.py` fica pra quando existir um settlement
   real pra validar contra (mesma cautela da pendência 4). Conferência
   amostral semanal (a outra metade da pendência original) nem começou
   - decisão desta sessão foi focar só na saída pra mercado sem
   resolver, e essa ficou bloqueada por dado antes de sair do papel.
10. ~~Agendador nunca rodou um dia inteiro em produção~~ — resolvido em
    2026-08-20 de um jeito diferente do planejado: em vez de validar
    `scripts/agendador.py` rodando 24h na máquina local do PM, os 5 jobs
    foram movidos pra `.github/workflows/*.yml` (GitHub Actions, cron),
    que roda sem depender do PC do PM estar ligado. `scripts/agendador.py`
    continua existindo pra uso local/manual, mas deixa de ser o caminho de
    produção. Dois bugs reais só apareceram na primeira execução de
    verdade (detalhe em `docs/HISTORICO.md`): input inválido
    `python-version` no `setup-uv` (corrigido), e `DATABASE_URL` de
    conexão direta do Supabase resolvendo IPv6 (sem rota nos runners do
    GitHub Actions) — corrigido trocando o secret pela connection string
    do **pooler** (`*.pooler.supabase.com`, ver nota em `.env.example`).
    Terceiro bug achado validando `backup-diario.yml`: `pg_dump` do
    `apt-get install postgresql-client` genérico ficava atrás da versão
    do servidor (Supabase = PG17) — corrigido instalando
    `postgresql-client-17` via repositório oficial do PostgreSQL no
    workflow. Os 5 workflows (`pipeline-diario`, `coleta-liquidacao`,
    `fechamento-diario`, `backup-diario`, `resumo-semanal`) já foram
    disparados manualmente e rodaram verde — pendência encerrada.
11. ~~Matcher recusava "Grêmio Novorizontino SP"~~ — resolvido em
    2026-08-20: `app.matcher.match_team_name` agora prioriza um match
    exato de UM time sobre empate com fuzzy de OUTRO time (antes os dois
    empatavam no teto de score e sempre iam pra `revisao_manual`, mesmo
    com um match exato em mãos). Dois times com alias exato idêntico
    continuam corretamente ambíguos (América-MG/RN, não regrediu).
    `migrations/0028` adiciona o alias que faltava.
12. Família "América-MG/América-RN" (dois times distintos que colidem
    depois de normalizar pra "america") continua sem resolução
    automática, por design (nunca escolhe entre dois aliases exatos
    empatados, mesma regra do caso Novorizontino/Grêmio). Reinvestigado
    em 2026-08-25: o exemplo antes citado aqui ("Novorizontino x América
    Mineiro" não resolvia odd por causa da família) **não reproduziu**
    contra o banco real - esse pick usa a forma curta "América-MG",
    vinculou normalmente (a desambiguação por janela de kickoff já
    funciona: só América-MG tinha fixture candidata na janela) e ficou
    `sem_odd` por falta de cobertura da OddsPapi pra Série B, sem
    relação nenhuma com a família. A forma completa "América Mineiro"
    (sem hífen) já resolve sem ambiguidade hoje (alias próprio distinto
    de "america"). A ambiguidade real só afeta a forma curta isolada -
    impacto medido hoje: 8 picks presos em `revisao_manual` por essa
    causa especificamente. Continua sem fix de código seguro (resolver
    genericamente arriscaria confundir os dois times de verdade); só
    resolve com alias manual quando um caso real específico for
    identificado, caso a caso, como no Novorizontino/Grêmio.
13. Volume real ainda baixo pra validar conflito de picks/limite diário do
    slate com dado de produção de verdade. Reconfirmado em 2026-08-25
    contra o Postgres real: só 11 picks já chegaram a `status=
    'vinculado'` na história do projeto, zero têm `status='descartado'`
    (nunca existiu um perdedor de conflito de verdade), zero fixtures
    têm mais de um pick vinculado no mesmo mercado (pré-condição pra
    conflito sequer existir), e o maior `daily_slate` já montado teve 3
    picks - nunca chegou perto do limite de 5 (`SLATE_MAX_PICKS`), então
    o corte por `confianca_tipster` também nunca disparou de verdade.
    Lógica só validada por teste sintético (`tests/test_slate.py`) até
    aqui - nada a mudar em código, só esperar o volume real crescer.
14. ~~`app/oddspapi.py::_parse_fixture` só reconhece mercado 1x2 sob uma
    chave fixa~~ — investigação de 2026-08-20 estava **errada**: a
    chave `"101"` estava presente nas duas fixtures de Série B
    testadas, com preços reais, mas `marketActive: false` (bet365 **e**
    betano, mesmas duas partidas) — mercado temporariamente suspenso,
    não indisponível por falha de parsing. O parser recusa corretamente
    (usar preço de mercado inativo violaria "piso publicado é sempre
    apostável de verdade"). Não é bug, não precisa de correção.
    **Hipótese confirmada em 2026-08-25**: rodei
    `parse_odds_by_tournaments_response` de verdade contra duas
    fixtures reais de Série B (bra.2, tournamentId 390) faltando 6h45
    pro kickoff — `marketActive: true` nas duas casas (bet365 e betano,
    as mesmas do achado original), preços 1x2 extraídos com sucesso,
    zero ignoradas. Confirma que o mercado ativa bem antes do kickoff
    (pelo menos até 6h45 de antecedência) — a suspensão vista em
    2026-08-20 foi um instantâneo pontual, não uma limitação estrutural
    de Série B. Nada a mudar no pipeline: ele já roda 1x/dia e capta o
    que estiver ativo no momento da coleta.

Para o "porquê" de qualquer decisão acima, ou o relato completo de uma
investigação (sondas, bugs de revisão de código, achados por fase), ver
[`docs/HISTORICO.md`](docs/HISTORICO.md).
