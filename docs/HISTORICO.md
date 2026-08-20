# Histórico detalhado do ZapTips

> Arquivo de arquivo (append-only). Contém o registro completo, fase a fase,
> de investigações, achados reais, bugs corrigidos e decisões tomadas ao
> longo do desenvolvimento. O `CLAUDE.md` na raiz do projeto tem só um
> resumo enxuto de cada fase; venha aqui quando precisar do "porquê"
> completo por trás de uma decisão ou do relato de uma investigação
> específica (ex.: sonda da ESPN, verificação do OddsPapi, achados de
> revisão de código). Continue atualizando este arquivo ao final de cada
> fase nova, com o mesmo nível de detalhe já usado abaixo — o `CLAUDE.md`
> só ganha a linha-resumo correspondente.

Sistema de curadoria de palpites esportivos com envio assistido por WhatsApp.
Especificação completa em `prompt-claude-code-palpites.md` — este arquivo
documenta o que foi implementado, o que a investigação real revelou e as
decisões tomadas ao longo do caminho. Em caso de conflito entre os dois,
este arquivo reflete o estado atual do código; o outro é a intenção original.

## Stack

- Python 3.11 (pinado via `uv`, ver `.python-version`). O Python 3.14 que
  também está instalado na máquina não foi usado: `playwright`/`telethon`,
  que entram nas próximas fases, ainda não garantem suporte total a 3.14.
- Gerenciador de pacotes/venv: `uv`.
- Postgres via Supabase. Migrations em SQL puro (sem Alembic), aplicadas por
  um runner próprio (`scripts/migrate.py`) — ver "Por que sem Alembic" abaixo.
- `httpx`, `tenacity`, `pydantic` / `pydantic-settings`, `psycopg[binary]` v3,
  `structlog`, `rapidfuzz`, `beautifulsoup4`, `anthropic` (entrou na Fase 3),
  `jinja2` (entrou na Fase 4), `fastapi` + `uvicorn` + `python-multipart`
  (entraram na Fase 5c, console local), `apscheduler` (entrou na Fase 7,
  `scripts/agendador.py`). `playwright` e `telethon` entram nas fases em
  que forem usados pela primeira vez, não antes.

### Por que sem Alembic

O schema evolui em blocos por fase (Fase 0, depois Fase 2 adiciona
`pick_blocos`, Fase 6 adiciona `master_ledger`, etc.), não em migrações
incrementais finas de ORM. Um runner de ~40 linhas que aplica `.sql` em
ordem e registra o que já rodou resolve isso sem trazer autogeração de
migration, que não tem schema de ORM para introspectar aqui. Reavaliar se
o projeto crescer a ponto de precisar de rollback automático ou branching
de schema.

## Estrutura

```
app/            pacote principal (config, futura logica de dominio)
migrations/     .sql numerados, aplicados em ordem por scripts/migrate.py
scripts/        CLIs e utilitarios (migrate.py, sonda_espn.py, sonda_oddspapi.py, seed_team_aliases.py, collect_fixtures.py, collect_results.py, collect_odds.py, collect_eagle_predict.py, collect_sda.py, extract_picks.py, link_picks.py, resolve_odds.py, build_slate.py, run_pipeline.py, users.py, subs.py, console.py)
tests/          pytest
```

## Comandos

`make` não está instalado neste ambiente Windows por padrão. Os alvos do
`Makefile` são só um atalho para os comandos `uv run` abaixo — use-os
diretamente se não tiver `make` (Git Bash com MSYS2/coreutils ou WSL têm):

| Objetivo | Comando |
|---|---|
| Instalar dependências | `uv sync --dev` |
| Aplicar migrations pendentes | `uv run python -m scripts.migrate` |
| Rodar testes | `uv run pytest` |
| Rodar a sonda da ESPN | `uv run python -m scripts.sonda_espn` |
| Rodar a verificação do OddsPapi | `uv run python -m scripts.sonda_oddspapi` |
| Popular team_aliases a partir da ESPN | `uv run python -m scripts.seed_team_aliases` |
| Coletar fixtures dos próximos 7 dias | `uv run python -m scripts.collect_fixtures` |
| Fechar partidas passadas (placar + stats) | `uv run python -m scripts.collect_results` |
| Capturar odds de referência do OddsPapi | `uv run python -m scripts.collect_odds` |
| Coletar palpites do Eagle Predict | `uv run python -m scripts.collect_eagle_predict` |
| Coletar palpites do SDA (recorrente) | `uv run python -m scripts.collect_sda` |
| Coletar palpites do SDA (backfill 90 dias) | `uv run python -m scripts.collect_sda --backfill` |
| Extrair palpites estruturados via Claude (Fase 3) | `uv run python -m scripts.extract_picks` |
| Vincular picks a fixtures reais (Fase 4) | `uv run python -m scripts.link_picks` |
| Resolver odd de referência/odd mínima (Fase 4) | `uv run python -m scripts.resolve_odds` |
| Montar o daily_slate do dia (Fase 4) | `uv run python -m scripts.build_slate` |
| Rodar o pipeline diário completo, com resume (Fase 5a) | `uv run python -m scripts.run_pipeline` |
| Forçar reexecução de uma etapa já `ok` (Fase 5a) | `uv run python -m scripts.run_pipeline --forcar-etapa odds` |
| Cadastrar assinante com opt-in (Fase 5b) | `uv run python -m scripts.users cadastrar --telefone +55... --opt-in-origem "..." --opt-in-evidencia "..."` |
| Registrar opt-in de novo (Fase 5b) | `uv run python -m scripts.users optin --telefone +55... --opt-in-origem "..." --opt-in-evidencia "..."` |
| Registrar opt-out (Fase 5b) | `uv run python -m scripts.users optout --telefone +55...` |
| Exportar dados de um usuário (LGPD, Fase 5b) | `uv run python -m scripts.users export --user-id <uuid> [--stdout]` |
| Registrar assinatura manual via Pix (Fase 5b) | `uv run python -m scripts.subs registrar --user-id <uuid> --inicio AAAA-MM-DD --fim AAAA-MM-DD --valor 49.90 --ref "..."` |
| Listar assinaturas vencendo (Fase 5b) | `uv run python -m scripts.subs vencendo [--dias 5]` |
| Subir o console local (Fase 5c) | `uv run python -m scripts.console` (abre em `http://127.0.0.1:8000`) |

`make setup`, `make migrate`, `make test`, `make sonda-espn`, `make sonda-oddspapi`, `make seed-team-aliases`, `make collect-fixtures`, `make collect-results`, `make collect-odds`, `make collect-eagle-predict`, `make collect-sda`, `make extract-picks`, `make link-picks`, `make resolve-odds`, `make build-slate`, `make run-pipeline`, `make subs-vencendo`, `make console` fazem a mesma coisa quando `make` está disponível (o backfill não tem alvo de `make` — só roda uma vez, na largada; comandos com argumento obrigatório como `cadastrar`/`registrar`/`export` não têm alvo de `make`, só a forma `uv run`).

## Variáveis de ambiente

Ver `.env.example` para a lista completa com comentários. Resumo dos
parâmetros de negócio e a decisão registrada para cada um:

| Variável | Valor | Decisão |
|---|---|---|
| `ODD_MINIMA_ABSOLUTA` | `1.40` | Piso alinhado ao range real do SDA (1.44–2.45), única fonte publicada no lançamento |
| `MARGEM_PCT` | `0.04` | Valor default proposto no documento, não questionado |
| `SLATE_MAX_PICKS` | `5` | Curadoria rápida, mensagem enxuta |
| `BANCA_INICIAL_PADRAO` | `1000` | — |
| `STAKE_PCT_PADRAO` | `0.02` | Conservador: banca aguenta sequência longa de reds com odds baixas (1.3–2.5) |
| `STAKE_MODO_PADRAO` | `fixo` | Isola qualidade do palpite do dimensionamento; ROI por fonte fica comparável (ver Fase 6b) |
| `MAX_ASSINANTES_ATIVOS` | `50` | Trava de código, ver Fase 5 |

`DATABASE_URL` preenchida com a connection string real do Supabase e a
migration 0001 rodou com sucesso contra o Postgres real em 2026-08-10 —
as 24 tabelas do schema foram confirmadas via `information_schema`, e uma
segunda execução de `scripts/migrate.py` confirmou que o runner é
idempotente (pula migration já aplicada). `.env` não é versionado
(`.gitignore`), a senha do banco tem caracteres especiais e precisou de
URL-encoding (`+ % @ ? !`) na connection string.

## Ambiente de execução

Decisão: roda só na máquina local do PM, sem servidor. Console sem
autenticação (Fase 5), scheduler via APScheduler em processo único (Fase 7).

## Decisões de negócio confirmadas

Além das 10 decisões já fechadas no documento original (assinatura sem
afiliado, sem trial, teto de 50 assinantes, ESPN como fonte única de
partidas, etc.), estas foram resolvidas nesta sessão:

- Lista de assinantes: captação do zero, não existe base prévia.
- Modo de stake: fixo sobre banca inicial (não proporcional).
- Tamanho do slate: 3 a 5 palpites por dia.
- `ODD_MINIMA_ABSOLUTA`: 1.40.
- Banca inicial / stake: 1000 / 2%.

Pendente, depende de dado real ainda não coletado:

- Ligas de lançamento e volume de partidas/dia — depende da coleta de 7
  dias completa (critério de aceite da Fase 1), não só da sonda.
- Conjunto de 4–6 torneios com cobertura ESPN+OddsPapi confirmada (escopo
  da quarentena) — Brasileirão Série A (`tournamentId=325`) e Série B
  (`390`) já confirmados com cobertura real de odds via OddsPapi (ver
  "Fase 1b" abaixo). Faltam confirmar os outros torneios do escopo
  (Champions, Libertadores, ligas europeias) com a mesma verificação.

## Fase 0 — Fundação: concluída

Schema criado em `migrations/0001_init.sql`, cobrindo todas as tabelas da
especificação original (`teams` até `bets`). Duas escolhas de tradução do
pseudo-SQL do documento para DDL real, ambas por simplicidade e não
listadas como decisão do PM porque são puramente técnicas:

- Enums viram `TEXT` + `CHECK`, não `CREATE TYPE ... AS ENUM`. Adicionar um
  valor novo fica um `ALTER TABLE ... DROP/ADD CONSTRAINT` em vez de um
  `ALTER TYPE` (que trava mais forte em Postgres antigo). Se algum dia isso
  incomodar, é uma migration reversível.
- Todo PK é `uuid default gen_random_uuid()`. Nativo do Postgres 13+, sem
  extensão — Supabase roda PG15+, então não precisa habilitar `pgcrypto`.
- `picks.bloco_id` existe como coluna `uuid` sem FK ainda, porque
  `pick_blocos` (decomposição de múltiplas do Andy's Bet Club) só é criada
  na Fase 2. Mesmo raciocínio para os relacionamentos que dependem de
  `master_ledger`, que só existe a partir da Fase 6.

## Fase 1a — Sonda da ESPN: concluída, com achados que mudam decisões da Fase 1

Rodada em 2026-08-10 com dado real: 3 partidas do Brasileirão Série A e 2
da Champions League (todas já encerradas), mais uma partida extra da
Série B para responder à pergunta sobre cobertura de estatísticas. JSON
bruto salvo localmente durante a investigação (não versionado — é
exatamente o "descartável" que a Fase 1a pede).

Script em `scripts/sonda_espn.py`. Duas notas de execução:

- **A borda da ESPN bloqueia com 403 qualquer `User-Agent` customizado**,
  inclusive um identificável tipo `ZapTips-Sonda/0.1`, e qualquer UA que
  contenha `Mozilla`. Só passaram UAs de biblioteca padrão sem modificação
  (`curl/*`, `python-httpx/*`). Isso contradiz a orientação do documento
  original ("User-Agent identificável") — **decisão pendente com o PM**:
  usar o UA default da lib HTTP (funciona, mas não identifica o cliente) ou
  investigar um header alternativo de identificação que não dispare o WAF.
  O coletor de produção da Fase 1 não deve copiar um UA customizado sem
  antes testar contra 403.
- Em 2026-08-10, a temporada 2026-27 da Champions ainda não tem fixtures
  publicadas no `site.api` (busca de 21 dias à frente devolveu zero
  eventos em todas as datas). Usei datas da temporada 2025-26, a mais
  recente com dado real, para responder as perguntas — não muda nenhuma
  conclusão estrutural sobre o formato do JSON.

### Respostas às 8 perguntas da Fase 1a

**1. Campos de horário e fuso.** `date` aparece no evento, na competição e
no header, sempre no formato `"2026-08-09T14:00Z"` — ISO 8601 em UTC, sem
exceção nas 6 partidas inspecionadas. Nenhuma conversão de fuso é
necessária na leitura, só no `atualizado_em`/`kickoff_utc` já ser gravado
como veio.

**2. `broadcasts` e `geoBroadcasts`.** Existem, mas **não apareceu nenhuma
emissora brasileira em nenhuma das 6 partidas do Brasileirão** — os 6
eventos vieram com `broadcasts: []` e `geoBroadcasts: []`. Nas 2 partidas
da Champions, os campos vieram preenchidos, mas só com emissoras dos EUA
(`Paramount+`, `CBSSN`), sempre com `region: "us"`. **Confirma a suspeita
do documento**: a tabela `broadcast_rules`, preenchida manualmente pelo PM,
é a fonte primária para o Brasil — a ESPN não vai ajudar aqui, pelo menos
não nas ligas e amostras testadas.

**3. Bloco de odds — achado mais importante da sonda.** Existe, tanto no
`scoreboard` (`competitions[0].odds`) quanto no `summary`
(`odds`/`pickcenter`), e **às vezes vem populado com casas reais**: uma
partida do Brasileirão trouxe `Bet 365` (moneyline 1x2) e outra trouxe
`DraftKings` (moneyline, spread e over/under). Bet365 é justamente uma das
casas licenciadas no Brasil que o SDA já cita. Isso é uma informação que
**não estava disponível quando o documento original foi escrito** — vale
uma conversa com o PM antes da Fase 1: talvez o bloco de odds nativo da
ESPN reduza a dependência do OddsPapi para os casos em que a Bet365
aparece, embora a cobertura pareça inconsistente (3 das 6 partidas do
Brasileirão vieram com `odds: [null]`, sem nenhuma casa). Não é substituto
confiável do OddsPapi, mas pode ser um complemento gratuito para os dias
em que aparecer.

Achado colateral: o campo `hasOdds` no `summary` **não é confiável** — veio
`false` numa partida que tinha, sim, um bloco `odds` com a DraftKings
preenchido. Nunca decidir presença de odds só pelo booleano; checar o
array de fato.

**4. Campos estáveis vs. variáveis.** Estáveis nas 6 amostras: `id`,
`date`, `status.type` (com `name`, `state`, `completed`, `detail`),
`competitors` com `score` e `linescores` (placar por tempo, resolve
`placar_ht_*` diretamente), `venue.fullName`. Variáveis: `broadcasts`,
`geoBroadcasts` e `odds` (às vezes vazios, às vezes populados, sem padrão
óbvio por liga). `week` veio sempre `None` para o Brasileirão — **não dá
para preencher `fixtures.rodada` a partir daí**; se isso importar, precisa
vir calculado ou de outra fonte.

**5. `sports.core.api.espn.com`.** Testado para um evento do Brasileirão.
Traz os mesmos dados, mas cada campo aninhado (venue, estatísticas, odds)
vem como uma referência `$ref` que exige uma requisição HTTP separada para
resolver — desenho normalizado, não um payload único. A única informação
extra vista que o `site.api` não expõe foi `boxscoreSource`/
`playByPlaySource` (`{"description": "S&A feed", "state": "full"}`), um
sinal de proveniência/completude do dado. Não compensa o custo de N+1
requisições para o que este projeto precisa. **Recomendação: não usar
`sports.core.api`, ficar só no `site.api`.**

**6. Estatísticas de escanteios e cartões (Série A, B e Champions).**
Confirmado nas 3 leagues: `boxscore.teams[].statistics` trouxe 28 métricas
em todas as amostras, incluindo `wonCorners`, `yellowCards`, `redCards`,
`totalShots`, `possessionPct`. Cobertura idêntica entre Série A, Série B e
Champions nas amostras testadas — nenhuma sinalização de dado ausente.

**7. Latência até o placar virar definitivo.** **Não respondida com dado
real.** As partidas amostradas já estavam encerradas havia dias/meses
quando a sonda rodou; medir esse intervalo exige poll perto do apito final
de uma partida ao vivo, não uma consulta pontual a histórico. Fica como
tarefa para a primeira execução do job de resultados na Fase 1 (comparar
`kickoff_utc + duração esperada` com o timestamp em que `status.type.completed`
vira `true` pela primeira vez).

**8. Marcação de adiada/cancelada/suspensa.** **Não confirmada com dado
real.** Uma varredura de ~36 consultas (3 ligas × 13 meses, granularidade
mensal) só encontrou dois valores de `status.type`: `STATUS_FULL_TIME` e
`STATUS_SCHEDULED` — nenhum jogo adiado ou cancelado caiu na amostra
esparsa. Existe um campo booleano `wasSuspended` na competição (visto como
`false` em todas as amostras), que sugere que suspensão fica registrada
ali em vez de mudar o `status.type`, mas isso não foi confirmado com um
caso real positivo. **Tratamento recomendado até haver confirmação:**
qualquer `status.type.name` fora do conjunto conhecido
(`STATUS_SCHEDULED`, `STATUS_IN_PROGRESS`/`STATUS_FIRST_HALF`/etc.,
`STATUS_FULL_TIME`) deve ser logado e mandado para revisão manual, nunca
mapeado silenciosamente para `agendada`/`encerrada`/`cancelada` por
suposição. Isso já é a postura geral do documento para essa API sem
contrato; aqui ela vale de forma mais literal, por falta de exemplo real.

### Consequência prática

A Fase 1 (matcher + coleta real de fixtures) pode começar. Duas decisões
que ficaram pendentes acima foram fechadas com o PM nesta sessão:

- **User-Agent do coletor de produção:** usar o default do `httpx`
  (`python-httpx/x.x`), sem customização. Já validado na sonda — qualquer
  UA identificável ou com "Mozilla" leva a 403.
- **Hierarquia de odds:** o bloco nativo da ESPN entra como 3º nível,
  antes do OddsPapi, quando trouxer casa licenciada no Brasil (ex.:
  Bet365). Hierarquia final: 1) fonte cita casa licenciada → 2) ESPN traz
  casa licenciada → 3) OddsPapi → 4) digitada na curadoria.

## Fase 1b — Verificação do OddsPapi: concluída

Rodada em 2026-08-10 com a chave gratuita real, respondendo às 5
perguntas da seção "Verificação antes de implementar" do documento de
especificação. Script descartável em `scripts/sonda_oddspapi.py`. JSON
bruto salvo localmente (não versionado, mesmo tratamento do `sonda_espn`).

**Achado que não estava no contrato documentado:** todo `GET` de fixture/
odds exige um parâmetro `sportId` não mencionado no documento original.
Descoberto via um endpoint não documentado, `GET /sports`, que lista os
`sportId` de cada esporte — soccer é `sportId=10`. Sem esse parâmetro a
API responde `400 MISSING_PARAMETER`.

### Respostas às 5 perguntas

**1. Slugs de casas brasileiras.** `bet365`, `betano` e `superbet` existem
em `/bookmakers` tanto na forma global (`bet365`, `betano`, `superbet`)
quanto em variante `.bet.br` (`bet365.bet.br`, `betano.bet.br`,
`superbet.bet.br`). **Mas a chave gratuita não tem acesso às variantes
`.bet.br`** — `/odds-by-tournaments?bookmaker=bet365.bet.br` devolve
`403 RESTRICTED_ACCESS` ("Restricted bookmaker(s)"). Só os slugs globais
funcionam no tier gratuito. **`betboom`, `novibet` e `vbet` (citados pelo
SDA) não aparecem em nenhuma variante** entre as 349 casas listadas —
não são suportadas pelo OddsPapi, gratuito ou não.

**Correção sobre o impacto disso na hierarquia** (a primeira versão deste
parágrafo superestimava a limitação): o nível 2 da hierarquia de odds
(documento original, seção "Hierarquia de origens") entra quando a fonte
cita casa **não licenciada** ou **não cita odd nenhuma** — nesses casos a
odd do OddsPapi não precisa ser da mesma casa que a fonte citou, é só uma
referência independente de qualquer casa bem coberta. Então
Novibet/BetBoom/VBET não existirem no OddsPapi **não trava o nível 2** —
essas três já são cobertas pelo **nível 1** (o SDA as cita como casas
licenciadas, usa a odd da própria fonte, sem chamar API nenhuma). A
limitação real e mais estreita: **qual(is) casa(s) usar como referência
fixa do nível 2**, e o fato de só existir a variante global (não `.bet.br`)
dessas três.

**Decisões tomadas com o PM (2026-08-10):**
- Nível 2 usa as **3 casas** (`bet365`, `betano`, `superbet`), não só uma
  — 3 chamadas/dia (~90/mês), dentro do orçamento de 250. Da 3 pontos de
  referência independentes por partida em vez de depender de uma casa só.
- Odds globais (não `.bet.br`) aceitas como estão, sem marcação especial
  em `odds_referencia.origem` (fica só `'oddspapi'`, não
  `'oddspapi_global'`) — é a única opção viável no tier gratuito, e a
  divergência entre mercado global e BR para a mesma partida/casa tende a
  ser pequena.

**2. Cobertura Brasileirão Série A/B.** Ambos têm `tournamentId` real e
cobertura de odds confirmada: Série A = `325` (160 partidas futuras),
Série B = `390` (171 futuras, 18 ao vivo no momento da sonda). Uma
chamada a `/odds-by-tournaments?bookmaker=bet365&tournamentIds=325,390`
devolveu 18 partidas, **todas com `hasOdds: true`**.

**3. Mercados confirmados na amostra (bet365, 18 partidas).** `1x2` (Full
Time Result), dupla chance (Double Chance Full Time), over/under em várias
linhas (0.5 a 7.5 gols), ambas marcam (Both Teams To Score), over/under de
cartões (Bookings, linhas 1 a 8), e variações por tempo (1º/2º tempo,
correct score, winning margin). **Escanteios não apareceram nesta amostra**
— não confirmado se o mercado existe e não veio nessas 18 partidas
específicas, ou se bet365 simplesmente não publica esse mercado no
OddsPapi. Fica como pendência para quando o adapter real for escrito.

**4. Tradução de marketId/outcomeId — achado que resolve o item sozinho.**
Existe um endpoint `GET /markets` **não documentado no material original**
que devolve a tabela de tradução inteira: 32.815 entradas (todos os
esportes), cada uma com `marketId`, `marketName`, `marketType`, `period`,
`handicap` e a lista de `outcomes` com nome. Não precisa montar a tabela
na mão — cachear esse endpoint (estático, mesmo tratamento de
`/bookmakers` e `/tournaments`: revalidar 1x/mês). Salvo em
`markets.json` no scratch da sessão para referência.

**5. Requisições consumidas.** A API **não expõe header de quota/rate
limit** na resposta — confirma que o rastreamento tem que ser feito só
via a tabela `api_quota` do próprio projeto, como o documento já previa.
A sonda completa (bookmakers + tournaments + sports + markets + duas
tentativas de odds-by-tournaments, uma delas restrita) consumiu cerca de
9 requisições da cota de 250/mês. Uma execução de produção já cacheando
bookmakers/tournaments/markets consome **1 requisição por casa por dia**,
batendo com a estimativa do documento (1 a 3/dia).

### Consequência prática

A verificação confirma que o OddsPapi cobre o caso base (Brasileirão A/B,
Bet365/Betano/Superbet) e destrava a Fase 1. Ajustes de contrato para o
adapter real, além do `sportId=10` obrigatório: usar sempre os slugs
globais das casas (nunca `.bet.br`), tratar escanteios como mercado não
confirmado até um teste mais amplo, e chamar `/odds-by-tournaments` uma
vez por dia para **cada uma das 3 casas** (bet365, betano, superbet),
não só uma.

## Fase 1c — Matcher de times (núcleo puro): concluído

`app/matcher.py`, com TDD (testes em `tests/test_matcher.py`, 20 casos,
100% de cobertura). Escopo desta etapa: só a lógica de normalização e
match, sem I/O — nem acesso a `team_aliases` no Postgres, nem CLI de
revisão (`python -m app.matcher review`). Isso fica para quando o
coletor de fixtures existir e `team_aliases` tiver dado real para casar
contra (ver "Próximos passos").

- `normalize_team_name`: minúsculas, remove acento (`unicodedata`), remove
  token de tipo de clube (`FC/EC/SC/CF/AC`, como prefixo ou sufixo,
  delimitado por palavra) **antes** de remover sufixo de estado
  (`-MG`, `/SP`) — nessa ordem porque um nome como `"Botafogo-RJ FC"` só
  tem o `-RJ` de fato no fim da string depois que o `FC` sai; a ordem
  inversa deixava o sufixo de estado sobrando quando vinha um token de
  clube depois dele. Colapsa espaços no fim.
- `match_team_name`: match exato contra `alias_normalizado`; senão fuzzy
  via `rapidfuzz.fuzz.token_set_ratio`, threshold 85.0 (`THRESHOLD_FUZZY`).
  Abaixo do threshold, sem alias nenhum, ou **empate entre times
  diferentes** (ex.: América-MG e América-RN normalizando para o mesmo
  `"america"`) → `status="revisao_manual"`, `team_id=None`, nunca chuta.
  Empate entre aliases do **mesmo** time prefere o alias exato,
  independente da ordem em que a lista foi passada (bug pego no
  code-reviewer antes de fechar a etapa — a ordem de uma query no banco
  não é garantida, então o resultado não podia depender dela).
- Revisado pelo agente `code-reviewer`: 2 achados MEDIUM (ordem do
  pipeline de regex perdendo o sufixo de estado; desempate
  não-determinístico) corrigidos nesta mesma etapa, com teste de
  regressão para cada um.
- Desambiguação por janela de kickoff (±36h) e a fila de revisão manual
  persistida (CLI `review`) ficam para quando o coletor de fixtures e
  `team_aliases` existirem de verdade — ver próximo item.

## Fase 1d — Seed de team_aliases a partir da ESPN: concluído

`scripts/seed_team_aliases.py`, rodado contra as 11 ligas do lançamento
(ver `app/ligas.py`) e o Postgres real em 2026-08-10. Populou **313 times
e 707 aliases**. Confirmado idempotente: segunda execução completa trouxe
0 times novos e 0 aliases novos.

- `app/espn_teams.py`: parser puro do payload de `/teams` (`tests/
  test_espn_teams.py`, 8 casos, 90% de cobertura — só `fetch_teams`, que é
  I/O de rede, fica fora, mesmo padrão do resto do projeto).
- **Achado que contraria o documento original:** o payload real da ESPN
  **não tem campo de apelido** (`nickname` não existe). Os campos
  disponíveis são `displayName`, `shortDisplayName`, `abbreviation`,
  `name` e `location` — todos viram alias candidatos, deduplicados. Na
  amostra do Brasileirão, só o Vasco teve `shortDisplayName` diferente do
  nome oficial (`"Vasco da Gama"` → `"Vasco"`); os outros 19 times vieram
  com os 4 campos de nome idênticos, só a abreviação variando. Isso
  significa que apelidos coloquiais de verdade (**"Galo"**, "Timão",
  "Peixe") **não vêm da ESPN** — só entram em `team_aliases` pelo
  fluxo de aprendizado manual (revisão aprovada vira alias novo), nunca
  no seed automático.
- `migrations/0002_team_aliases_unique.sql`: `unique (team_id,
  alias_normalizado)` em `team_aliases`, necessária pro upsert do seed
  funcionar com `ON CONFLICT`. Rodada contra o Postgres real.
- `app/db.py`: wrapper fino de conexão (`get_connection()`), usado pelo
  script de seed e por qualquer código futuro que precise do Postgres.
- **Achado real rodando o matcher contra os 707 aliases seedados** (não
  um teste sintético): o nome `"Galo"` batia por fuzzy contra `"GAL"`
  (abreviação do Galatasaray) com score 85.71 — acima do threshold, mas
  sem nenhuma relação real entre os times, só coincidência de caracteres
  em string curta. Corrigido em `app/matcher.py`: aliases/nomes com menos
  de 5 caracteres normalizados (`MIN_LEN_FUZZY`) só entram na comparação
  por match exato, nunca por fuzzy. Teste de regressão em
  `tests/test_matcher.py`. Também validei os casos de ambiguidade real
  contra dado real: `"Atletico-MG"`, `"Vasco"` e `"Botafogo FC"` caem
  corretamente em `revisao_manual` (times diferentes normalizam pro mesmo
  alias — exatamente o cenário que a janela de kickoff ±36h vai resolver
  quando o coletor de fixtures existir).
- Revisado pelo `code-reviewer`: 3 achados MEDIUM (exceção estreita
  demais no fetch por liga — só `HTTPStatusError`, não pega timeout/erro
  de conexão; `upsert_team` fazia SELECT-então-INSERT sem `ON CONFLICT`,
  diferente de `upsert_alias` e não seguro contra corrida; lógica de
  upsert sem teste automatizado). Os 3 corrigidos: exceção ampliada para
  `httpx.HTTPError`, `upsert_team` reescrito para usar `ON CONFLICT ...
  RETURNING` como `upsert_alias`, e `tests/test_seed_team_aliases.py`
  adicionado com um cursor fake (sem precisar de Postgres real) cobrindo
  `upsert_team`/`upsert_alias`/`seed`.

## Fase 1e — Coletor de fixtures: concluído

`app/espn_fixtures.py` + `scripts/collect_fixtures.py`, com TDD (`tests/
test_espn_fixtures.py` 16 casos, `tests/test_collect_fixtures.py` 5
casos). Rodado contra as 11 ligas e o Postgres real em 2026-08-10: **42
fixtures novas** nos próximos 7 dias, **0 ignoradas**, **0 com time não
resolvido** (o seed da Fase 1d cobriu 100% dos times que apareceram).
Confirmado idempotente rodando duas vezes seguidas.

- Escopo deliberadamente restrito a agendamento: `espn_event_id`, liga,
  temporada, `home_team_id`/`away_team_id` (resolvidos direto por
  `espn_team_id`, sem fuzzy match — o `scoreboard` da ESPN já traz o
  `id` do time, o mesmo semeado na Fase 1d), `kickoff_utc`, `status`,
  `estadio`. **Placar e placar do intervalo ficam fora**: o `scoreboard`
  devolve `score: "0"` mesmo para partida que nem começou, então usar
  esse campo aqui produziria 0-0 falso para jogo agendado. Fica para o
  job de coleta de resultados (próximo item), que lê o `/summary` — muito
  mais completo para isso.
- Mapeamento de status usa `status.type.state` (`pre`/`in`/`post`), mais
  estável que a lista aberta de `status.type.name`. `state="post"` sem
  `completed=true`, ou `wasSuspended=true`, viram `EventoIgnorado` (nunca
  mapeados por suposição) — exatamente a pergunta 8 da sonda da Fase 1a,
  que não tinha caso real confirmado.
- Revisado pelo `code-reviewer`: 1 achado HIGH (campo do JSON com `null`
  explícito, não só ausente — ex.: `"venue": null` — quebrava os `.get()`
  encadeados com `AttributeError` não tratado, o que abortaria a coleta
  inteira das 11 ligas por causa de 1 payload estranho; a API da ESPN não
  tem contrato de estabilidade, então isso é um risco real, não teórico)
  e 1 MEDIUM (time não resolvido virava `NULL` sem log, difícil de
  rastrear depois). Os 2 corrigidos: `parse_scoreboard_response` isola
  qualquer evento que falhe o parsing em `EventoIgnorado` em vez de
  deixar a exceção subir, e `collect_fixtures.py` loga toda resolução de
  time que falhar. Testes de regressão para os dois.

## Fase 1f — Job de coleta de resultados: concluído

`app/espn_summary.py` + `scripts/collect_results.py`, com TDD (`tests/
test_espn_summary.py` 16 casos, `tests/test_collect_results.py` 6 casos).
Fecha partidas passadas: busca fixtures com `status != 'encerrada'` e
`kickoff_utc` há mais de 2h, lê `/summary`, grava placar final, placar do
intervalo e estatísticas por time (`fixture_stats`, origem `'espn'`).

- **Idempotente por construção**, não por deduplicação: a própria query
  (`status != 'encerrada'`) exclui fixtures já fechadas de execuções
  futuras, sem precisar de estado externo. `fixture_stats` ganhou
  `unique (fixture_id, time_id)` (`migrations/0003_fixture_stats_unique.sql`)
  só como rede de segurança para upsert.
- Placar e estatísticas só são extraídos quando o status resolve pra
  `encerrada` — uma partida `ao_vivo` tem número parcial que ainda muda;
  gravar isso como se fosse final seria o mesmo erro que a política de
  status já evita para adiada/cancelada.
- **Validado contra `/summary` real** de uma partida encerrada de verdade
  (Cruzeiro 3x1 Mirassol, 2026-08-09): placar final, placar do intervalo
  (1-1 no HT) e as 5 estatísticas relevantes (escanteios, cartões
  amarelos/vermelhos, finalizações, posse) bateram exatamente com o JSON
  bruto. A query SQL do job também rodou contra o Postgres real (0
  fixtures elegíveis no momento, esperado — as 42 fixtures coletadas na
  Fase 1e ainda estão todas no futuro). O fluxo de ponta a ponta contra
  uma fixture real do banco só é observável horas depois, quando alguma
  passar de kickoff+2h — não bloqueia o restante da Fase 1.
- **Regra do documento original ainda não implementada:** "partida adiada
  ou cancelada deve marcar todos os palpites vinculados como void". Não
  dá para implementar agora por dois motivos, não só um: (1) `map_status`
  nunca produz `adiada`/`cancelada` — a política de "nunca mapear por
  suposição" (Fase 1a) significa que esses casos sempre caem em
  `EventoIgnorado`, então o gatilho para essa regra ainda não existe no
  código; (2) a tabela `picks` está vazia (Fase 2 não começou), não tem o
  que marcar como `void` ainda. Revisitar quando as duas condições
  existirem.
- Revisado pelo `code-reviewer`: 1 HIGH (mesma classe de bug já vista no
  coletor de fixtures — `"statistics": null` explícito num time
  descartava um placar final que já tinha sido parseado com sucesso,
  porque o erro subia até o try/except externo e jogava o evento inteiro
  fora) e 1 MEDIUM (transação única do Postgres ficava aberta durante o
  loop inteiro de chamadas rate-limited à ESPN — uma falha no meio do
  lote descartava, via rollback, o trabalho de rede já pago das fixtures
  anteriores). Os 2 corrigidos: parsing de estatísticas isolado num
  try/except próprio (falha vira stats vazias, nunca descarta o placar já
  válido) e o script separado em fase de rede (sem transação aberta) e
  fase de escrita (curta, sem sleep), mesmo padrão do `collect_fixtures.py`.
  De quebra, consolidei `RATE_LIMIT_SECONDS` (estava duplicado em 3
  módulos) em `app/espn_client.py`.

## Fase 1g — Adapter do OddsPapi: concluído, com um pivô de design no meio

`app/oddspapi.py` + `scripts/collect_odds.py`, com TDD (`tests/
test_oddspapi.py` 15 casos, `tests/test_collect_odds.py` 19 casos).
Captura odd de referência do mercado 1x2 (nível 2 da hierarquia, ver Fase
1b) para bra.1/bra.2, gravando em `odds_referencia` com `origem='oddspapi'`.

### Primeira versão: casar por horário quebrou contra dado real

O design inicial casava fixture do OddsPapi com fixture da ESPN só por
`(liga, kickoff_utc exato)` — parecia razoável porque `/odds-by-tournaments`
só devolve `participant1Id`/`participant2Id` numéricos, sem nome de time,
e uma chamada extra só para nomes pareceria desperdício de cota.

Rodando contra dado real: **~60% das partidas do Brasileirão colidem em
horário** (rodadas usam sempre os mesmos 3-4 horários padrão de
transmissão, não só a rodada final — isso não é edge case raro, é a
norma). O log mostrou 6 colisões span 12 de 21 fixtures só na primeira
rodada testada.

**Correção:** existe um endpoint `/participants` (não documentado no
material original, achado nesta sessão) que resolve o ID numérico pra
nome — catálogo grande (~19.500 times, todos os esportes) mas estático,
1 chamada só. O nome resolvido passa pelo `app.matcher` já existente
(mesmo threshold fuzzy, mesma política de nunca chutar ambiguidade)
contra `team_aliases`. `participant1Id` é sempre o mandante — confirmado
contra o exemplo real Palmeiras x Fluminense, com um fallback que checa a
ordem invertida e loga (`participant1_pode_nao_ser_mandante`) sem gravar
nada, caso a suposição quebre para algum torneio/casa. Fixture agora casa
por `(liga, home_team_id, away_team_id)`, não mais por horário.

### Segundo achado real: `team_aliases` tem times de categorias diferentes colidindo

Mesmo com nome, sobrou ambiguidade real: `team_aliases` foi semeada
(Fase 1d) cobrindo as 11 ligas do lançamento, incluindo sub-20, reservas e
copas regionais — times diferentes que às vezes normalizam pro mesmo
alias que o time principal. Corrigido com `filtrar_aliases_relevantes`:
antes de casar, restringe o catálogo de aliases só aos times que
realmente têm fixture na janela atual (bra.1/bra.2), eliminando colisão
com times de outras competições. Isso sozinho subiu a taxa de match de
56% pra 67% (60→72 odds gravadas em 108 possíveis).

**Ambiguidade residual, documentada e aceita:** mesmo filtrado, times que
compartilham nome genérico entre estados colidem — ex.: "Atlético-MG" e
"Atlético-GO" ambos normalizam pra `"atletico"` (o mesmo regex de sufixo
de estado que corretamente une "Cruzeiro-MG"→"Cruzeiro" também funde
clubes diferentes que só se distinguem pelo estado). **Isso não é bug —
é o matcher recusando corretamente chutar entre dois times reais**,
mesmo comportamento validado desde a Fase 1c (América-MG/RN). Times assim
(família Atlético, família Botafogo) ficam sem odd do OddsPapi até o
fluxo de aprendizado manual (aprovação de match vira alias novo — ainda
não construído, é Fase 2/3) resolver caso a caso.

### Resultado final rodando contra dado real

- **84 linhas em `odds_referencia`**, ~72 de 108 combinações possíveis
  casadas (67%) na última rodada completa.
- **Cota**: 11 chamadas usadas no mês (3 bookmakers + 1 `/participants`,
  por execução), bem dentro do orçamento de 250.
- Idempotente via `ON CONFLICT` em `casas.slug_oddspapi`,
  `api_quota(provedor, mes_referencia)` e índice de expressão em
  `odds_referencia` (migrations 0004-0005). `league_map` semeada só com
  bra.1/bra.2 confirmados (migration 0006) — outras ligas do documento
  original ficam pendentes da mesma verificação real antes de entrar.
- Revisado pelo `code-reviewer` em 3 rodadas ao longo do pivô: 1 CRITICAL
  (a API key vazava pro log via `httpx.HTTPStatusError.__str__()`, que
  inclui a URL completa da resposta com o query param `apiKey` —
  corrigido com `_erro_sem_segredo()`, que nunca loga `str(exc)` bruto de
  chamada autenticada), 3 HIGH (duas variações da mesma classe de bug já
  vista em `espn_fixtures.py`/`espn_summary.py` — campo `null` explícito
  e sub-item malformado derrubando dado já válido — mais `/participants`
  sem nenhuma guarda contra corpo `null`/malformado) e 3 MEDIUM (cota
  subcontada em falha de rede, sem sinal de diagnóstico se
  `participant1Id=mandante` quebrar, ausência de teste pro catálogo
  global de matching). Todos corrigidos com teste de regressão.

## Fase 2, Fonte 1 — Coletor do Eagle Predict: concluído

`app/eagle_predict.py` + `scripts/collect_eagle_predict.py`, com TDD
(`tests/test_eagle_predict.py` 13 casos, `tests/test_collect_eagle_predict.py`
16 casos). Canal público do Telegram, HTML sem Telethon, captura o texto
do post inteiro em `raw_picks` sem tentar extrair mercado/seleção/odd —
isso é trabalho da Fase 3, que ainda não começou.

### Dois achados reais que contrariam o documento original

**1. O marcador de tip do documento não existe no canal real.** O
documento cita `"Football Betting Tip"` (ASCII liso) como marcador para
identificar post útil. O canal real usa fonte Unicode estilizada
(mathematical sans-serif bold) que varia entre `"Prediction of the Day"`
e `"Football Tip 2/3/4"` — esse texto nunca aparece literalmente.
Inspecionando 20 mensagens reais (9 tips genuínos, 11 promo/outros, zero
falso positivo/negativo), o marcador estável encontrado foi **`"Odds @"`**
— texto plano, sempre presente em post de tip real, ausente de post
promocional.

**2. Bug de scraping pego durante a própria investigação (não em
produção).** Uma mensagem que é *resposta* a outra tem **dois** blocos
com a classe `tgme_widget_message_text` no DOM: um é a citação truncada
da mensagem respondida (classe extra `js-message_reply_text`), outro é o
texto real da própria mensagem (classe extra `js-message_text`). Um
seletor genérico pega o primeiro que aparecer — que pode ser a citação
truncada e irrelevante. Um post real (`"Congrats to all who won!"`, sem
odd nenhuma) foi erroneamente classificado como tip porque a citação
truncada continha `"Odds @"` de uma mensagem antiga que ele respondia.
Corrigido usando sempre o seletor composto `.js-message_text`. Teste de
regressão específico para esse caso.

### Resultado rodando contra dado real

- **Backfill de 90 dias**: 358 posts verificados, **95 com marcador de
  tip**, todos gravados em `raw_picks` com texto completo (4 tips por
  post, nada truncado — confirmado manualmente contra uma amostra).
- Confirmado idempotente: segunda execução (incremental, via `after=`)
  trouxe 0 novos, contagem de `raw_picks` não mudou.
- Fonte nasce em quarentena (`sources.quarentena = true`, já é o default
  da coluna desde a Fase 0) — sair é decisão do PM, nunca configuração
  default.
- Revisado pelo `code-reviewer`: 1 HIGH (falha de rede no meio da
  paginação derrubava o backfill inteiro sem salvar nada — só as outras
  fases já tinham essa proteção, faltava aqui; corrigido com o mesmo
  padrão try/except das demais) e 2 MEDIUM (`hash_conteudo` não era
  escopado por fonte — dois canais de Telegram diferentes poderiam
  colidir no mesmo hash já que `message_id` só é único por canal, não
  globalmente; corrigido incluindo o nome do canal no hash — e faltava
  teste pro limite de segurança de páginas). Todos corrigidos com teste
  de regressão.

## Fase 2, Fonte 2 — Coletor do SDA (Sites de Apostas): concluído

`app/sda.py` + `scripts/collect_sda.py`, com TDD (`tests/test_sda.py` 22
casos, `tests/test_collect_sda.py` 15 casos). Site WordPress, REST
bloqueada (403, testado nesta sessão) — HTML com `bs4`, como o documento
previu. Dois modos: recorrente (só cards "ativo", padrão) e backfill
(`--backfill`, só "encerrado", uma vez só, 90 dias).

### Achados reais que confirmam o documento (dessa vez ele acertou)

Diferente do Eagle Predict, aqui a investigação prévia do documento
("já investigada") bateu com o dado real em quase tudo — validei antes
de implementar e não achei surpresa que invalidasse o design:

- **Duas paginações independentes, mesma URL `/page/N`** — confirmado via
  `.pagination` (2 elementos: um vai até página 2, outro até 5847).
  Identifico o status de cada card pelo rótulo próprio (`"Terminado"` ou
  `"Começa em"`), nunca pela posição, exatamente como o documento pediu.
- **Cards vazios por autor, sistemático**: Fabio Storino apareceu no
  backfill real com múltiplos posts sem tipster/data/hora/oneliner —
  `raw_picks.texto_bruto` ficou só com o título, sem crashar.
- **Slug divergente do título**: o exemplo do documento
  ("Anderlecht x Hammarby") apareceu literalmente no backfill real, com
  slug contendo `qualificatorias-liga-europa` que o título não menciona.
- **"Palpite em Destaque" repetido**: o backfill trouxe 91 cards já
  conhecidos entre as 760 páginas percorridas — consistente com o
  documento avisar que o post em destaque do topo repete um post da
  lista em várias páginas. A deduplicação por `hash_conteudo` (URL +
  texto) absorveu isso sem duplicar nada.

### Resultado rodando contra dado real

- **Modo recorrente**: 3 cards ativos no momento da execução (a maioria
  dos ~10 vistos na investigação já tinha começado/encerrado só pelo
  tempo passar durante a sessão). Confirmado idempotente: segunda
  execução trouxe 0 novos.
- **Modo backfill**: 760 cards percorridos, **669 novos**, corte em
  exatamente ~90 dias (intervalo real gravado: 12/05 a 10/08/2026).
  **672 linhas totais em `raw_picks`, 672 hashes distintos, 672 URLs
  distintas** — zero duplicata.
- **6 casas licenciadas semeadas** (`migrations/0008`-`0009`): Bet365,
  Betano e Superbet já existiam (Fase 1g, via OddsPapi) e mantiveram seu
  `slug_oddspapi`; Novibet, BetBoom e VBET entraram novas, sem
  `slug_oddspapi` (confirmado sem cobertura no OddsPapi desde a Fase 1b).
- Revisado pelo `code-reviewer`: **aprovado direto**, só 1 MEDIUM (gap de
  teste pro caso "página inteira sem data parseável não aciona o corte
  do backfill" — comportamento documentado e intencional, só faltava
  teste de regressão) e 1 LOW (nome de casa duplicado como literal em
  dois arquivos, sem risco hoje). Ambos endereçados.

## Revisão holística pós-Fase 2: concluída

Pedido explícito do PM antes de avançar pra Fase 3 ("revise antes"). Até
aqui cada arquivo novo tinha sido revisado isoladamente (5-6 rodadas de
`code-reviewer`, uma por coletor); essa rodada olhou os arquivos juntos,
atrás do que só aparece numa visão cruzada — duplicação entre scripts
irmãos, nomes colidindo entre módulos, drift de convenção. Testes (167),
migrations (0001-0009, todas aplicadas sem drift) e uma contagem de linha
por tabela do banco (todas batendo com o que este arquivo documenta)
bateram limpo primeiro.

Dois achados reais, nenhum bug de comportamento (nada gravava dado
errado), mas ambos exatamente o tipo de coisa que revisão por-arquivo não
pega:

- **`upsert_source` duplicada palavra-por-palavra** em
  `collect_eagle_predict.py` e `collect_sda.py` — um terceiro coletor
  reaproveitaria a cópia errada e uma mudança futura (ex.: um campo novo
  em `sources`) só atualizaria uma das duas sem ninguém perceber.
  Extraído para `app/sources.py`, único lugar agora.
- **Nome de constante colidindo entre módulos sem relação**:
  `collect_results.py` tinha uma constante local
  `ANTECEDENCIA_MINIMA_HORAS = 2` (quanto esperar *depois* do kickoff pra
  fechar o resultado) com o **mesmo nome** de `settings.
  antecedencia_minima_horas` (Fase 5/7: janela *antes* do kickoff pra
  entrar no envio) — dois conceitos diferentes, mesmo valor por
  coincidência, nome idêntico por acidente. Renomeada para
  `HORAS_APOS_KICKOFF_PARA_FECHAR`, com comentário explicando a
  distinção pra não repetir a confusão quando a Fase 5/7 chegar.

Achado LOW registrado mas não corrigido (custo/benefício não compensa
mexer em arquivos já testados e em produção por uma questão cosmética):
nomes de constante de rate-limit divergem entre módulos
(`RATE_LIMIT_SECONDS` em `espn_client.py`/`eagle_predict.py`,
`COOLDOWN_SECONDS` em `oddspapi.py`, `RATE_LIMIT_RECORRENTE_SEGUNDOS`/
`RATE_LIMIT_BACKFILL_SEGUNDOS` em `sda.py`). Nenhum risco funcional.

Segurança, injeção de SQL, imports não usados, código morto e uso
consistente do `FakeCursor` compartilhado: nada encontrado. Suíte
completa (166 testes após a extração) e os três scripts tocados
(`collect_eagle_predict.py`, `collect_sda.py`, `collect_results.py`)
rodados ao vivo de novo pra confirmar que a refatoração não quebrou nada
em produção.

## Fase 3 — Extração estruturada via Claude API: concluída, com uma pendência real (custo)

`app/extraction.py` (prompt, schema JSON, parsing defensivo) +
`scripts/extract_picks.py` (CLI que busca `raw_picks` pendentes, chama a
extração em lotes e grava em `picks`), com TDD (`tests/test_extraction.py`
14 casos, `tests/test_extract_picks.py` 13 casos — 189 testes no total no
projeto). Duas migrations novas: `0010_raw_picks_extraido_em.sql`
(coluna que rastreia se um raw_pick já foi processado, independente de
ter gerado 0 ou N picks — sem ela não dá pra distinguir "post sem
palpite" de "ainda não processado") e `0011_picks_campos_extraidos.sql`
(`time_casa`, `time_fora`, `competicao`, `data_referencia`, `unidades`,
`tipster` em `picks` — colunas que faltavam pros campos que a extração
devolve). Ambas aplicadas contra o Postgres real em 2026-08-10.

**Decisões tomadas com o PM nesta sessão:**

- **Modelo: Haiku 4.5** (`claude-haiku-4-5`), não o modelo mais capaz
  disponível. Extração de campos curtos (time, mercado, odd, casa) de
  texto curto e informal é uma tarefa direta de classificação/extração, e
  esse job roda continuamente sobre volume crescente de `raw_picks` (não
  é uma chamada única) — custo por token pesa mais aqui do que numa
  tarefa de raciocínio complexo. Critério de aceite do documento original
  (85%+ de acerto numa amostra de 20 posts reais) ainda não foi validado
  — falta a chamada real acontecer.
- **`mercado` sem CHECK constraint no banco** (discrepância real entre o
  schema do documento original, que propõe um enum, e o schema já
  existente desde a Fase 0, que deixou a coluna como `text` livre):
  validação fica só na aplicação (`MERCADOS_VALIDOS` em
  `app/extraction.py`), com fallback pra `"outro"` se o modelo devolver
  um valor fora da lista. Não vale reabrir o schema por isso agora.
- **`casas.aliases` continua vazio**: normalização de `casa_apostas`
  contra `casas` é só case-insensitive exato (nome + aliases, sem fuzzy)
  — as 6 casas seedadas na migration 0009 não têm alias nenhum ainda.
  Population de aliases fica para depois de ver, com dado real da
  extração rodando, quais variações de grafia os tipsters realmente usam
  (mesmo princípio de "investigar antes de supor" já aplicado o resto da
  sessão) — não faz sentido advinhar agora.

**Achado de design, pego pelo `code-reviewer` antes de qualquer chamada
real:** o schema de saída original do documento (`{"palpites": [...]}`)
é por-post; como o requisito "batche vários posts por chamada" exige N
posts numa única resposta, o schema real usado envolve isso num nível
`resultados` indexado por `post_id` (= `raw_picks.id`), pra dar pra
religar cada palpite extraído ao raw_pick de origem. Descoberta
importante nessa mesma revisão: **structured outputs não garante que o
modelo responda por todo post_id do lote** — se um post for omitido na
resposta, ele não pode ser silenciosamente contado como "sem palpite"
para sempre. `parse_resposta` devolve também o conjunto de `post_id`s que
de fato apareceram na resposta, e só esses são marcados como
`extraido_em` — um post omitido fica pendente e é reenviado no próximo
run.

**3 achados HIGH do `code-reviewer`, todos corrigidos antes de qualquer
run contra dado real:**

- **`uuid.UUID` vs `str` quebrava a comparação de conjuntos e
  provavelmente o `UPDATE` final.** `psycopg` devolve colunas `uuid` como
  objeto `uuid.UUID` por padrão; o `post_id` que volta no JSON do modelo
  é sempre `str`. Sem normalizar, `ids_do_lote - post_ids_respondidos`
  nunca dava vazio (o aviso de "posts ausentes" disparava sempre, mesmo
  quando o modelo respondia certo), e `update raw_picks ... where id =
  any(%s)` rodando com uma lista de `str` contra coluna `uuid` era
  candidato real a erro de tipo em runtime — o que, por rodar na mesma
  transação dos `insert into picks`, derrubaria os inserts de todo o run
  no rollback. Corrigido normalizando pra `str` na leitura
  (`buscar_raw_picks_pendentes`) e com cast explícito
  (`any(%s::uuid[])`) no update, mesmo com a normalização já resolvendo a
  causa raiz — defesa em duas camadas por ser barata e o tipo de bug que
  não dá pra pegar sem rodar contra o Postgres real.
- **Campos extraídos pelo modelo (time, competição, data, unidades) eram
  computados e descartados** — `upsert_pick` só gravava
  `mercado`/`selecao`/`odd`/`casa_id`/`confiança`/`status`, sem nenhuma
  coluna em `picks` pros outros campos do schema. Como `extraido_em` é o
  único gate contra reprocessamento, esse dado seria perdido de forma
  permanente no momento em que o raw_pick fosse marcado — e a Fase 4
  (matching contra `fixtures`, via `picks.fixture_id`) depende
  diretamente de `time_casa`/`time_fora`/`data_referencia` existirem.
  Corrigido com a migration 0011 e gravação completa em `upsert_pick`.
  De quebra, `tipster` (coluna que já existia em `picks` desde a Fase 0
  mas nunca era populada por nada) passou a vir de `raw_picks.autor` —
  dado já coletado na Fase 2, não é campo extraído pelo modelo.
- **`processar_lotes` só tratava `anthropic.APIError`** — uma resposta
  sem bloco de texto (`stop_reason="refusal"`) ou JSON truncado
  (`stop_reason="max_tokens"` no meio de um lote grande) levantam
  `StopIteration`/`json.JSONDecodeError`, que não são `APIError` e
  derrubariam `processar_lotes` inteiro, descartando em memória o
  resultado de lotes anteriores já processados com sucesso (a fase de
  escrita só roda depois de todos os lotes) — quebra do mesmo princípio
  de isolamento por lote já usado nos coletores da Fase 1/2. Corrigido
  ampliando o `except`.

Achado MEDIUM corrigido: `confianca_extracao` (usada para o gate
`extraido`/`revisao_manual`) não tinha limite de faixa — um valor fora de
`[0, 1]` devolvido pelo modelo passaria direto pro gate. `_parse_palpite`
agora limita (`max(0.0, min(1.0, ...))`).

### Autenticação: investigada, resultado negativo

`ANTHROPIC_API_KEY` segue vazia. CLI `ant` (v1.22.1) baixado e instalado
nesta sessão (`C:\Users\ebort\bin\ant.exe`, direto do release do GitHub —
não existe pacote/instalador pronto pra Windows fora dos binários da
release). `ant auth login` (rodado pelo próprio PM, interativo, abre
navegador) autenticou com sucesso via OAuth contra a conta pessoal do
PM — mas uma chamada de teste (`client.messages.create`, `max_tokens=20`)
devolveu `400 invalid_request_error`: *"Your credit balance is too low to
access the Anthropic API."* **Confirmado, sem ambiguidade: a assinatura
Pro do Claude.ai (chat) não cobre chamadas à API**, nem autenticando via
OAuth — é a mesma pool de créditos pagos, faturamento separado do chat,
independente do método de autenticação. `scripts/extract_picks.py`
continua correto e pronto para uso, mas **precisa de créditos de API
reais** pra rodar (comprar em console.anthropic.com > Plans & Billing) —
isso é uma restrição de produto da Anthropic, não algo que o código
resolve.

### Backlog de 767 raw_picks: extraído manualmente, sem custo de API

Decisão do PM diante da falta de crédito: em vez de esperar, os 767
`raw_picks` pendentes foram extraídos **manualmente por agentes do Claude
Code** (rodando dentro desta sessão, já coberta pela assinatura Pro, sem
consumir a pool de créditos da API) — não uma chamada real a
`client.messages.create`. Metodologia: os 767 posts foram exportados em 8
lotes de ~100, cada lote processado por um subagente `general-purpose`
seguindo exatamente as mesmas regras do `SYSTEM_PROMPT`/`_PALPITE_SCHEMA`
de `app/extraction.py` (mesmo enum de mercado, mesma semântica de
`confianca_extracao`, mesma exigência de nunca inventar campo, mesma
obrigação de responder por todo `post_id` do lote mesmo com 0 palpites).
Os 8 arquivos de resultado foram então consolidados e gravados no
Postgres **reaproveitando o código de produção já testado**
(`app.extraction.parse_resposta`, `scripts.extract_picks.upsert_pick` /
`carregar_casas` / `marcar_extraidos`) — não um caminho de escrita
paralelo.

Dois lançamentos em paralelo (4 subagentes de uma vez) bateram no limite
de sessão do Claude Code no meio do processo (erro de sessão, não de
código) — resolvido relançando um lote de cada vez, sequencial, até os 8
completarem.

**Resultado gravado no Postgres real (2026-08-10):**
- **1046 picks** inseridos a partir dos 767 `raw_picks` (todos marcados
  `extraido_em`, nenhum pendente restante).
- Status: 1045 `extraido`, 1 `revisao_manual` (confiança 0.65 — post
  genuinamente ambíguo, "Lens" sem verbo, corretamente sinalizado em vez
  de chutado).
- Mercado: `over_under` 524, `1x2` 333, `ambas_marcam` 168, `handicap`
  11, `outro` 8, `cartoes` 1, `escanteios` 1.
- `casa_id` resolvido em 100% dos picks (1046/1046) — as casas citadas
  batem exatamente com o nome cadastrado (sem precisar de alias ainda).
- `tipster` populado em 666/1046 (o resto são posts do Eagle Predict, que
  nunca gravou `autor` em `raw_picks` desde a Fase 2 — não é um bug desta
  fase).

**Critério de aceite (85%+ em amostra de 20 posts reais): validado, 20/20
(100%).** Amostra aleatória reprodutível (`random.seed(42)`) de 20
`raw_picks` processados, revisão manual de cada um contra o texto
original — todos os campos (times, mercado, seleção, odd, casa) batem,
incluindo os casos de julgamento (`BTTS` → `ambas_marcam`, `"Home win
HC-1.5"` → `handicap`, `"1X"` double-chance → `1x2`, o bucket mais
próximo no enum) e o único caso ambíguo da amostra corretamente roteado
pra `revisao_manual`. **Ressalva importante:** essa validação mede a
qualidade do *design do prompt/schema*, não o comportamento do Haiku 4.5
especificamente — a extração em si foi feita por agentes do Claude Code,
não pela API. Vale reconfirmar a acurácia numa amostra nova quando
`scripts/extract_picks.py` rodar contra a API de verdade.

**Critério de aceite (custo por 100 posts, medido e documentado): não
satisfeito — pendência real.** Sem chamada real à API, não existe
`response.usage` pra medir. A estimativa de preço (`$1`/`$5` por milhão
de tokens do Haiku 4.5) já está no script (`PRECO_INPUT_POR_MTOK`/
`PRECO_OUTPUT_POR_MTOK` em `scripts/extract_picks.py`), mas o número real
só existe depois de `scripts/extract_picks.py` rodar contra a API de
verdade, com créditos, contra `raw_picks` novos (os 767 atuais já foram
processados e não vão reaparecer como pendentes).

### Decisão permanente (2026-08-13): não vai haver créditos de API — extração assistida por agente vira o processo real, não um fallback temporário

Até aqui este documento tratava a falta de `ANTHROPIC_API_KEY` como um
bloqueio temporário ("quando houver créditos..."). O PM confirmou
nesta sessão que **não vai comprar créditos de API** — restrição de
orçamento, não um "ainda não". Isso muda o status de
`scripts/extract_picks.py`: o código continua correto e testado, mas
**não existe expectativa de que ele rode contra a API de verdade**. A
etapa `extração` do pipeline (`run_pipeline.py`) vai fechar `degradado`
permanentemente, por design agora — não é mais um sinal de "falta
alguém comprar crédito", é o estado normal e esperado.

**Processo definido com o PM pra substituir isso, permanente:** repetir
sob demanda o que já funcionou no backlog de 767 posts (ver acima) —
quando o PM pedir (ex.: "extrai os picks pendentes"), rodar um ou mais
subagentes seguindo o mesmo `SYSTEM_PROMPT`/`_PALPITE_SCHEMA` de
`app/extraction.py` sobre os `raw_picks` com `extraido_em is null`, e
gravar o resultado reaproveitando o mesmo caminho de escrita já testado
(`app.extraction.parse_resposta` + `scripts.extract_picks.upsert_pick`/
`carregar_casas`/`marcar_extraidos`) — nunca um caminho de escrita
paralelo. Coberto pela assinatura Pro (Claude Code), não pela pool de
API. Três outras opções foram consideradas e descartadas nesta sessão:
automatizar isso no `scripts/agendador.py` (esbarra numa limitação
técnica real — o agendador não pode invocar um subagente do Claude Code
sozinho, precisaria de um humano pedindo), abandonar extração
automática e depender só do "Adicionar palpite manual" do console
(descartaria o valor dos coletores Eagle Predict/SDA), e trocar de
provedor de LLM (retrabalho maior, reabriria a validação de acurácia da
Fase 3 do zero).

**Consequência prática:** os critérios de aceite da Fase 3 que dependiam
de rodar contra a API real (custo medido por 100 posts, reconfirmação
da acurácia do Haiku 4.5 especificamente) **não vão ser satisfeitos
nunca**, por decisão de produto — não são mais pendências a fechar, são
critérios de aceite que não se aplicam mais a como o produto realmente
vai operar. A validação de 20/20 (100%) já feita mede o que importa daqui
pra frente: a qualidade do design do prompt/schema, que é o que os
subagentes de fato executam a cada rodada.

## Fase 4 — Curadoria e templates: concluída (escopo sem console/assinantes)

Três módulos novos + scripts + migrations, todos com TDD (253 testes no
projeto todo) e validados contra o Postgres real. Reaproveita
`app/matcher.py` (Fase 1c) e `odds_referencia` (Fase 1g) em vez de
duplicar lógica.

### Pré-requisito não coberto pelo documento original: vincular picks a fixtures

O documento assume "picks vinculados a fixtures" como dado de entrada da
curadoria — não existia esse vínculo ainda. Achado real desta sessão:
as datas do backfill da Fase 3 (maio–agosto de 2026, texto histórico de
tipster) quase não se sobrepõem com a janela de 7 dias que
`collect_fixtures.py` mantém. Reprocessar os coletores ao vivo
(`collect_fixtures`/`collect_eagle_predict`/`collect_sda`, de graça, sem
custo de API) não trouxe post novo no momento — mas revelou **1
sobreposição real**: Goiás x Londrina (Série B), que serviu de caso de
validação ponta a ponta pro resto da fase.

`app/pick_linking.py` + `scripts/link_picks.py`: resolve
`time_casa`/`time_fora` via `app.matcher` (mesmos `team_aliases` da Fase
1d, filtrados aos times que têm fixture agendada agora — mesmo princípio
de `filtrar_aliases_relevantes` já usado em `collect_odds.py`), escolhe a
fixture certa numa janela de ±36h em torno de `data_referencia` (mesma
tolerância já usada pro OddsPapi na Fase 1g). Nunca chuta: time não
resolvido ou sem fixture candidata fica `extraido` (tenta de novo depois
— a maioria dos 1046 picks referencia ligas fora do escopo de 11
competições semeado na Fase 1d); mais de uma fixture candidata na janela
vira `revisao_manual`. Rodado contra dado real: **1 vinculado** (Goiás x
Londrina, confirmado manualmente), 1044 seguem `extraido`.

### Hierarquia de odds de referência (níveis 1 e 2) + odd mínima

`app/odds_resolution.py` + `scripts/resolve_odds.py`: nível 1 (fonte cita
casa licenciada + `odd_citada`, direto de `picks`) e nível 2
(`odds_referencia`/OddsPapi, só mercado `1x2`, usa o **mínimo** entre as
3 casas — decisão desta sessão: o produto promete um piso, não uma
cotação, então o valor mais conservador entre as casas rastreadas é o
que sustenta essa promessa). Nível 3 (ESPN) e nível 4 (manual/console)
ficam fora de escopo — adapter ESPN não existe, console é Fase 5.
`odd_minima = max(odd_referencia*(1-MARGEM_PCT), ODD_MINIMA_ABSOLUTA)`,
sempre arredondado pra baixo. Sem odd em nenhum nível → `sem_odd`; odd
abaixo do piso → `descartado` (exclusão automática, nunca só um alerta —
documento original). Motivo de exclusão gravado em `picks_orfaos`
(`app/picks_orfaos.py`, compartilhado com `build_slate.py` — extraído já
na 2ª ocorrência, mesmo critério da revisão holística pós-Fase 2).
Migration 0012 deu unique a `picks_orfaos.pick_id` pra isso funcionar com
`ON CONFLICT`. Rodado contra dado real: o único pick vinculado (mercado
`over_under`, sem `odd_citada`, sem cobertura OddsPapi pra esse mercado)
ficou corretamente `sem_odd` — validação de que o pipeline não inventa
odd quando não tem de onde tirar.

### Motor de montagem do slate + correção de design numa migration já aplicada

`app/slate.py` + `scripts/build_slate.py`: filtra picks `vinculado` com
odd resolvida e fixture com kickoff nas próximas 24h; detecta conflito
(mesmo fixture+mercado, seleções diferentes) e resolve por consenso —
empate manda o grupo inteiro pra `revisao_manual`, nunca decide sozinho;
aplica `SLATE_MAX_PICKS` cortando pelos de maior `confianca_tipster`
(decisão desta sessão, não especificada no documento — pick cortado só
por limite **não muda de status**, só o perdedor de conflito vira
`descartado`). Gera `daily_slates`/`slate_picks` com status `rascunho`.

**Erro de design pego e corrigido antes de virar dívida técnica:** a
migration `0013_daily_slates.sql` (recém-aplicada) tinha
`unique(data)` em `daily_slates` — mas o documento original diz
explicitamente que "correção depois da aprovação gera um slate novo com
referência ao anterior" (slate aprovado é imutável), o que exige mais de
um slate por data numa cadeia de correções. `unique(data)` proibiria
exatamente isso. Como ainda não existia código dependendo da suposição
errada, corrigido direto com uma migration nova
(`0014_daily_slates_correcao.sql`: remove o `unique`, adiciona
`criado_em`/`substitui_slate_id`) em vez de carregar o erro adiante —
"slate atual de uma data" virou consulta (`order by criado_em desc
limit 1`), não mais garantia de unicidade no schema.

### Revisão de código: 1 HIGH real + 2 MEDIUM + 1 LOW, todos corrigidos

- **HIGH:** `normalizar_selecao_1x2` (resolução de odd nível 2) preferia
  `time_casa` cegamente quando o nome de um time era substring do outro
  (ex.: "Grêmio" dentro de "Grêmio Novorizontino") ou quando os dois
  normalizavam igual (família Atlético-MG/GO, ambiguidade já documentada
  desde a Fase 1g) — classificava vitória do time de fora como vitória
  da casa, puxando a odd errada pro `odd_referencia`/`odd_minima` que o
  assinante veria. Corrigido: se os dois times batem (ou nenhum bate),
  devolve `None` em vez de chutar `casa` — mesma cautela que
  `MIN_LEN_FUZZY` já aplica em `app/matcher.py` pro mesmo tipo de risco.
- **MEDIUM:** detecção de conflito em `app/slate.py` comparava texto
  bruto de `selecao` — duas fontes concordando no mesmo resultado com
  fraseado diferente ("Home win" vs "Vitória do Fluminense") eram
  tratadas como desacordo, diluindo consenso real. Corrigido reusando
  `normalizar_selecao_1x2` pra mercado `1x2` antes de agrupar; outros
  mercados continuam comparando texto bruto (não existe normalizador
  equivalente ainda, e faltaria comparar `linha`, que a extração nem
  populou — limitação conhecida, documentada, não resolvida
  especulativamente).
- **MEDIUM:** `calcular_odd_minima` usava `float`/`math.floor` pra uma
  garantia de produto explícita ("piso arredondado pra cima quebra a
  promessa") — imprecisão binária podia empurrar o resultado um centavo
  pro lado errado (confirmado com caso real: odd 2.75, margem 4% deveria
  arredondar pra 2.64, `float` dava 2.63). Corrigido com `Decimal` +
  `ROUND_DOWN`.
- **MEDIUM** (`scripts/build_slate.py`, `criar_ou_reaproveitar_slate`):
  não tinha consciência da cadeia de correção que a migration 0014
  habilitou — um rascunho de correção manual (referenciando um slate já
  aprovado) podia ser apagado/reconstruído por uma rodada automática.
  Corrigido: `buscar_rascunho_existente` só reaproveita rascunho
  "original" (`substitui_slate_id is null`); `existe_correcao_em_andamento`
  aborta o script inteiro se houver correção em progresso pra aquela
  data. TOCTOU entre o SELECT e o INSERT do slate ficou sem lock
  explícito, por decisão: a arquitetura do projeto já exclui execução
  concorrente ("roda só na máquina local do PM... scheduler em processo
  único", Fase 7) — documentado no código, revisitar só se isso mudar.
- **LOW:** `renderizar_mensagem` compilava `saudacao_template` como
  template Jinja2 de verdade — sem risco hoje (só as 4 strings fixas de
  `SAUDACOES` passam por ali), mas um vetor de injeção de template se um
  dia uma saudação por assinante (Fase 5) usar esse parâmetro. Corrigido
  pra substituição literal (`str.replace`), não compilação.

### Template de mensagem (função pura, sem geração real ainda)

`app/messaging.py`: Jinja2, `rodape_legal` obrigatório por design (sem
default no dataclass + checado de novo em tempo de render — "não torne
esse campo opcional no código" levado a sério nos dois pontos), 4
saudações sorteadas, horário convertido pro fuso do usuário via
`zoneinfo` (stdlib, sem dependência nova). `RODAPE_LEGAL` vira setting em
`app/config.py` com rascunho de texto (18+, jogo responsável, opt-out).
**Não gera `messages` de verdade**: o loop "pra cada assinante ativo com
assinatura válida, gera uma mensagem respeitando preferência/idempotência"
depende de existir pelo menos um assinante real, e a Fase 5 (console +
captação) ainda não começou — "Lista de assinantes: captação do zero,
não existe base prévia" segue valendo. A função de render está pronta e
testada; falta o que renderizar pra alguém de verdade.

### Resultado final rodando contra dado real

- `scripts/link_picks.py`: 1 vinculado (Goiás x Londrina), 1044 seguem
  `extraido` (sem fixture coletada ainda pra maioria — esperado, não é
  erro).
- `scripts/resolve_odds.py`: o único vinculado ficou `sem_odd` (mercado
  `over_under`, sem `odd_citada` na fonte, sem cobertura OddsPapi pra
  esse mercado) — comportamento correto, não bug.
- `scripts/build_slate.py`: slate de 2026-08-10 criado com 0 picks
  incluídos (nenhum candidato passou pela resolução de odds ainda) —
  gerado, persistido, idempotente (reaproveita o rascunho em reruns).
- Nenhum critério de aceite do documento original (idempotência, usuário
  sem preferência recebe slate completo, usuário sem assinatura não
  gera mensagem, conflito nunca chega sem decisão explícita, horário
  correto por fuso) foi validado ainda com dado que *popule* o slate de
  verdade — o volume real disponível hoje é baixo demais pra isso. Vale
  revisitar assim que `collect_fixtures`/`collect_eagle_predict`/
  `collect_sda` rodarem recorrentemente (Fase 7) e picks/fixtures
  passarem a se sobrepor no dia a dia.

## Fase 5a — Orquestrador de pipeline: concluída

`app/pipeline.py` (catálogo de etapas, máquina de estado, laço de
orquestração puro `avancar_etapas` — 99% de cobertura, só uma linha de
defesa em profundidade comprovadamente inalcançável com o `ETAPAS` atual
fica sem teste) + `app/pipeline_runs.py` (acesso a `pipeline_runs`/
`pipeline_stages`, 100% de cobertura) + `scripts/run_pipeline.py`, com
TDD (313 testes no projeto). Liga em sequência os scripts das Fases 1-4
(`collect_fixtures`, `collect_eagle_predict`+`collect_sda`,
`extract_picks`, `link_picks`, `collect_odds`+`resolve_odds`,
`build_slate`), sem crons independentes por etapa — exatamente o que o
documento original pede ("Não use crons independentes por tarefa").

Migrations `0015_pipeline_stages_unique.sql` (`unique(run_id, etapa)`,
necessária pro upsert de etapa) e `0016_picks_orfaos_tipo.sql`
(`picks_orfaos` ganhou coluna `tipo`, separando o uso já existente desde
a Fase 4 — pick excluído da curadoria, sem contador — do uso novo desta
fase — pick sem fixture ainda, com contador de tentativas). As duas
aplicadas contra o Postgres real; a migration 0016 fez backfill de 1
linha existente (`tipo='excluido'`), sem ambiguidade.

### Decisões tomadas com o PM nesta sessão (D1-D6)

- **D1 — escopo do contador de tentativas.** 1044 dos 1046 picks não têm
  fixture hoje, mas por dois motivos bem diferentes: liga fora do escopo
  das 11 competições semeadas (nunca vai resolver, seja qual for o
  contador) ou times resolvidos com a partida ainda não coletada (o
  "órfão" de verdade que a spec descreve, linha 1021). Contar tentativa
  pra qualquer pick sem fixture inundaria a fila de revisão manual com
  ~1000 itens inacionáveis em 5 execuções. Decisão: `app/pick_linking.py`
  ganhou o campo `motivo` em `ResultadoVinculo` (`sem_times_no_pick`,
  `time_nao_resolvido`, `sem_fixture_na_janela`, `None` quando vinculado)
  e só `sem_fixture_na_janela` conta tentativa. Validado com dado real: a
  primeira execução gerou **192 linhas em `picks_orfaos` (tipo
  `sem_fixture`)**, não ~1000 — confirma que a distinção captura o
  cenário certo.
- **D2 — quando contar.** Só quando a etapa `fixtures` trouxe fixture
  nova nesta execução (`resultados["fixtures"].detalhe["novas"] > 0`),
  leitura literal da linha 1023 ("toda vez que a etapa fixtures traz
  partidas novas"). Validado: a segunda execução do dia (fixtures pulada,
  já `ok`) não tocou nenhum contador de `picks_orfaos` — confirmado
  consultando a tabela antes/depois.
- **D3 — extração sem crédito de API.** A etapa `extracao` degrada (não
  falha) quando há `raw_picks` pendentes e `ANTHROPIC_API_KEY` está
  vazia; 0 pendentes fecha `ok`. Validado: a execução real teve 7 posts
  novos (6 do SDA, 1 do Eagle Predict) coletados pela etapa `coleta` e a
  etapa `extracao` fechou `degradado` com `{"motivo":
  "anthropic_api_key_ausente", "pendentes": 7}` — o resto do pipeline
  (matching, odds, slate) seguiu rodando normalmente.
- **D4 — `QUEUE_ENABLED` não bloqueia a montagem do slate.** Fora de
  escopo na prática nesta fase (não há geração de mensagem ainda, isso é
  Fase 5d) — só documentado pra não esquecer quando a fila existir.
- **D5 — `collect_results.py` fica fora das 6 etapas.** Nenhuma mudança;
  revisitar em Fase 6/7, onde o timing de "rodar horas depois do
  kickoff" pode ser desenhado como job próprio, não bolado numa etapa
  matinal.
- **D6 — fuso da `data_referencia`.** `America/Sao_Paulo`, não UTC.
  `app/pipeline.py` ganhou `data_operacional()` (usa `zoneinfo`, Brasil
  não observa horário de verão desde 2019 mas a fonte de verdade é a
  tzdata do SO, não um offset fixo hardcoded) e `scripts/build_slate.py`
  (já em produção desde a Fase 4) foi ajustado pra usar a mesma função —
  sem isso, um run às 22h de Brasília abriria o dia seguinte em UTC.

### Design: import + `try/except` por etapa, não subprocess

Cada um dos 8 scripts de etapa ganhou uma função `executar() ->
ResultadoEtapa` (extract-method puro do corpo de `main()`, comportamento
de CLI preservado) que `scripts/run_pipeline.py` importa e chama
diretamente — decisão registrada no plano desta fase: subprocess isolaria
melhor contra crash total, mas perderia `itens_ok`/`itens_erro`/
`detalhe_json` estruturado (teria que fazer parsing de print), que é
exigência central da spec pra etapa `degradado`. Nenhum teste existente
chamava `main()` de nenhum script (verificado antes do refactor), então a
suíte de 253 testes anteriores foi uma rede de regressão real.

Só a etapa `fixtures` pode fechar o run como `falhou` (aborta tudo,
spec). As outras 5 nunca abortam: um `try/except Exception` na borda de
cada etapa em `app.pipeline.avancar_etapas` converte qualquer exceção não
tratada em `degradado` (nunca embute `str(exc)` bruto no detalhe —
precedente da Fase 1g, erro de chamada autenticada vaza query string com
`apiKey`); e mesmo que um adaptador *devolva* `status="falhou"` sem
levantar exceção, `avancar_etapas` sanitiza pra `degradado` se a etapa
não for `fixtures` — defesa em profundidade, não caminho normal.

### Resultado rodando contra dado real (2026-08-11)

Primeira execução do dia: `fixtures` ok (2 novas, 41 atualizadas),
`coleta` ok (6 SDA + 1 Eagle Predict), `extracao` degradado (ver D3),
`matching` ok (192 novos órfãos `sem_fixture`, 0 vinculado — nenhuma das
partidas novas bateu com um pick pendente ainda), `odds` ok (69 odds
gravadas, 1 sem match), `slate` ok (0 candidatos — nenhum pick com odd
resolvida e fixture nas próximas 24h). Run fechou `degradado` (só por
causa da `extracao`), exatamente o esperado sem crédito de API.

Três verificações adicionais confirmaram os critérios de aceite da spec
com dado real, não só com fakes:

- **Resume**: reexecutar no mesmo dia pulou as 5 etapas já `ok`, retentou
  só `extracao` (continua degradada), e **não consumiu nenhuma chamada
  extra de cota do OddsPapi** (`api_quota` ficou em 15 chamadas antes e
  depois).
- **`--forcar-etapa slate`**: reexecutou `slate` mesmo já `ok`, sem
  tocar nas outras etapas já fechadas (exceto `extracao`, que sempre
  retenta por não estar `ok`).
- **Recuperação de crash**: uma etapa forçada manualmente pra `rodando`
  (simulando um processo interrompido) foi detectada e resetada pra
  `pendente` no início da próxima execução (`etapas_travadas_resetadas`
  no log), e reexecutada normalmente.

## Fase 5b — CLI de assinantes + opt-in/opt-out: concluída

`app/users.py` (identidade, consentimento, export LGPD) + `app/subs.py`
(teto de assinantes, registro de assinatura, painel de vencimento) +
`scripts/users.py`/`scripts/subs.py` (CLIs argparse), com TDD (360
testes no projeto, subiu de 314). `app/users.py` e `app/subs.py` em
100% de cobertura. Migration `0017_users_opt_in_evidencia.sql` aplicada
contra o Postgres real — `users` estava comprovadamente vazia
(confirmado por query antes de aplicar, não só por inferência), então o
`NOT NULL` em `opt_in_em`/`opt_in_origem`/`opt_in_evidencia` (coluna
nova) não precisou de backfill.

### Decisões tomadas com o PM nesta sessão (D1-D5)

- **D1 — `app/` vs `scripts/`.** O documento original nomeia os comandos
  como `python -m app.users`/`python -m app.subs`, mas nenhum módulo em
  `app/` no projeto todo tem `argparse`/`main()` (confirmado por grep) —
  a convenção real desde a Fase 0 é `app/` puro + `scripts/` fino, sem
  exceção. Mantida a convenção, documento tratado como desatualizado
  nesse ponto (CLAUDE.md é autoritativo sobre o documento onde
  divergem, regra já estabelecida). Comando real:
  `uv run python -m scripts.users ...` / `scripts.subs ...`.
- **D2 — definição de "assinante ativo" pro teto de 50.** Não é "tem
  assinatura cobrindo hoje" (deixaria estourar o teto num mês futuro
  mesmo com a lista de hoje cheia) — é o **pico de assinantes distintos
  em qualquer dia do período da assinatura sendo registrada**, contando
  a proposta como se já existisse (`UNION ALL` + `count(distinct
  user_id)` antes de comparar contra o teto). Duas propriedades
  garantidas por essa contagem: uma pessoa com duas assinaturas
  sobrepostas ocupa uma vaga só, e uma renovação de quem já está ativo
  nunca é recusada por estar exatamente no limite (validado contra o
  Postgres real com `MAX_ASSINANTES_ATIVOS=1`, ver abaixo).
- **D3 — opt-in obrigatório na criação.** `criar_usuario` exige origem +
  evidência, e o banco trava com `NOT NULL` (migration 0017). Seguro
  porque `users` estava vazia — depois de gente real cadastrada, exigir
  isso teria significado inventar consentimento retroativo.
- **D4 — opt-out não mexe em `users.status`.** Só `opt_out_em` muda;
  `status` continua sendo estado de pagamento (`ativo`/`inadimplente`/
  etc.), não de consentimento — misturar os dois impediria responder
  "essa pessoa saiu, ou só parou de pagar?" mais pra frente (Fase 6,
  LGPD).
- **D5 — opt-in de novo depois de opt-out.** `telefone_e164` é único, e
  a spec não cobre alguém que volta depois de sair. Adicionado
  `scripts.users optin`: limpa `opt_out_em` e grava evidência de
  consentimento nova (nunca um "undelete" silencioso).

### Dois achados reais pegos só rodando contra o Postgres de verdade

Nenhum dos dois apareceu nos 356 testes com `FakeCursor` — só existem
quando o driver real (`psycopg`) recusa uma constraint:

1. **Referência de pagamento duplicada vazava traceback cru.** A
   migration 0017 adiciona `unique index` parcial em
   `subscriptions.referencia_pagamento` justamente pra pegar o erro
   humano de rodar `registrar` duas vezes (histórico do terminal) — mas
   a violação (`psycopg.errors.UniqueViolation`) não estava capturada,
   e o operador via um traceback do driver em vez de uma mensagem
   legível. Corrigido: `app/subs.py` agora captura e relança como
   `ReferenciaPagamentoDuplicada`, com teste de regressão usando um
   `FakeCursor` que simula a violação (`_CursorQueViolaUniqueNoInsert`
   em `tests/test_subs.py`).
2. **`--user-id` sem validação, achado pelo `code-reviewer`.** Mesma
   classe de bug do item 1: um UUID mal colado (erro humano real, tão
   plausível quanto o da referência duplicada) chegava direto numa
   comparação `= %s::uuid` e o Postgres recusava com
   `InvalidTextRepresentation`, vazando traceback em dois comandos
   (`subs registrar`, `users export`). Corrigido com um conversor
   compartilhado `scripts/_cli_args.py` (`uuid_arg`, mesmo padrão de
   `_decimal_arg`/`_data_arg` já usados pra `--valor`/`--inicio`/
   `--fim`), testado (100% cobertura) e validado ao vivo: o comando
   agora recusa com mensagem de uso do `argparse` e `exit 2`, não
   traceback.

### Resultado rodando contra dado real (2026-08-11)

Usuário real cadastrado (o próprio operador, telefone real, opt-in
`"autocadastro do operador"`) — não um fixture. Duas assinaturas reais
registradas (uma renovação da outra), painel `vencendo --dias 40`
confirmado mostrando `dias_restantes` e `ja_renovado` corretos (virou
`true` só depois da segunda assinatura existir). Teto testado com
`MAX_ASSINANTES_ATIVOS=1` temporário (restaurado a 50 logo depois): um
segundo usuário descartável (telefone obviamente fictício,
`+5500000000001`, apagado do banco ao fim do teste) foi corretamente
**recusado**, e uma renovação do usuário já ativo foi corretamente
**aceita** no mesmo teto de 1 — a propriedade central de D2, confirmada
com dado real, não só com `FakeCursor`. `export --stdout` conferido:
`valor` sai como string `"49.90"`, nunca float; as 3 tabelas sem dado
(`user_preferences`, `messages`, `user_bankroll_config`, `bets`)
aparecem como `[]`, não ausentes. `optout` testado duas vezes seguidas:
idempotente, segunda chamada reporta "já estava fora" sem mexer na
data.

`.gitignore` ganhou `export_*.json` — um export LGPD commitado seria o
pior desfecho possível dessa função.

## Fase 5c — Console FastAPI (abas Saúde + Curadoria): concluída

Primeira superfície HTTP do projeto: `app/console/` (pacote, não módulo
único — primeira feature do projeto que precisou disso: `rules.py`
puro, `queries.py`/`acoes.py` DB-shape, `deps.py`/`main.py`/
`rotas_saude.py`/`rotas_curadoria.py` de wiring fino, `templates/` e
`static/`) + `scripts/console.py` (launcher, `uvicorn` em
`127.0.0.1:8000`, nunca `0.0.0.0`). Com TDD (454 testes no projeto,
subiu de 360) — `app/console/{rules,queries,acoes}.py` em 100% de
cobertura, `rotas_curadoria.py` em 95% (o resto é I/O de conexão,
convenção do projeto). Sem autenticação, decisão já fechada desde o
"Ambiente de execução" no topo deste documento — não revisitada aqui.

Duas migrations: `0018_slate_picks_odd_referencia_origem.sql`
(`slate_picks` ganhou a origem da odd de referência, faltava pra
mostrar "com origem" na curadoria) e
`0019_daily_slates_curadoria_iniciada.sql` (`daily_slates.
curadoria_iniciada_em`, ver achado abaixo).

### Decisões tomadas com o PM nesta sessão (D1-D8)

- **D1 — sem botão "rodar agora".** O console só lê e reage ao estado
  do `pipeline_runs` de hoje; disparar `scripts.run_pipeline` continua
  manual pelo terminal (ou pelo scheduler da Fase 7, ainda não feita).
  Um botão que dispara um job de minutos dentro de uma requisição HTTP
  não combina com a arquitetura atual.
- **D2 — filtro de quarentena implementado, fontes continuam
  quarentenadas.** Eagle Predict e SDA seguem `quarentena = true` (a
  decisão de tirar uma fonte é baseada em performance medida, não em
  querer ver algo na tela) — a aba de Curadoria e o motor de slate
  ficam corretamente vazios até essa decisão futura. Ver achado
  CRITICAL abaixo: o filtro só existia na exibição antes desta sessão.
- **D3 — palpite manual adiado pra Fase 5d.** Sem uso imediato (slate
  real tem 0-1 itens hoje); a fonte sintética `console_manual` fica
  para quando o volume justificar.
- **D4 — proteção do rascunho em curadoria.** `daily_slates.
  curadoria_iniciada_em`, carimbado por toda ação de escrita
  (`app/console/acoes.py::marcar_curadoria_iniciada`) antes de tocar
  `slate_picks`. `scripts/build_slate.py` ganhou
  `existe_curadoria_em_andamento` (abort completo do run, mesmo padrão
  já usado pra `existe_correcao_em_andamento`) + o guard em
  `buscar_rascunho_existente` (`curadoria_iniciada_em is null`) como
  defesa em profundidade. Sem isso, um re-run automático (Fase 7)
  apagaria — ou, pior, **duplicaria** — o rascunho em curadoria, porque
  o `unique(data)` foi removido já na Fase 4 (migration 0014) para
  permitir a cadeia de correção.
- **D5 — alerta de divergência entre odd citada e odd de referência:
  não implementado nesta sessão.** Ficou fora do escopo por tempo;
  fica como pendência explícita (ver "Próximos passos"), não uma
  omissão silenciosa.
- **D6 — painel de assinaturas vencendo na aba Saúde, não só na Fase
  5d.** `app.subs.listar_vencendo` (Fase 5b) já existia; reaproveitado
  direto em `rotas_saude.py`, 3 linhas.
- **D7 — `OPERADOR_NOME` como setting (`app/config.py`), default
  `"console"`.** Grava em `daily_slates.curado_por` na aprovação.
- **D8 — "fontes fora do ar" derivado do histórico de
  `pipeline_stages`, não de uma escrita nova em `sources.
  ultimo_sucesso_em`.** Essa coluna nunca foi escrita por nenhum
  coletor da Fase 2 e não valia a pena mexer nos arquivos de produção
  só para isso — `dias_fora_por_fonte` já responde a pergunta com dado
  que já existe.

### Achados reais dos revisores — um CRITICAL e dois HIGH corrigidos antes de fechar a fase

Pedido explícito de `code-reviewer` e `security-reviewer` em paralelo,
por ser a primeira superfície HTTP do projeto. Nenhum destes apareceu
nos testes com `FakeCursor`/`TestClient` originais — só a leitura
humana achou:

- **CRITICAL (code-reviewer): o filtro de quarentena era só de
  exibição.** `carregar_itens_slate` (a query que alimenta a aba) já
  filtrava `sources.quarentena is not true` desde a primeira versão —
  mas **nada** impedia um pick de fonte quarentenada de entrar em
  `slate_picks` pelo motor automático (`scripts/build_slate.py::
  buscar_picks_candidatos` não tinha esse filtro) nem de ser
  reinserido manualmente via "usar esta seleção" na resolução de
  conflito (`conflitos_por_fixture` também não filtrava). Um slate
  assim apareceria vazio na tela — e aprovável, porque
  `bloqueios_de_aprovacao` só via o que a query filtrada mostrava.
  Corrigido em três camadas: filtro na origem
  (`buscar_picks_candidatos`, `conflitos_por_fixture`) **e** uma
  checagem defensiva nova, direto em `slate_picks`
  (`existe_pick_quarentena_no_slate`), chamada em `post_aprovar_slate`
  antes de qualquer aprovação — mesmo que os dois primeiros filtros
  falhem por algum motivo futuro, a aprovação recusa.
- **HIGH (security-reviewer): rotas de escrita nunca confirmavam que
  `slate_id` era o rascunho *atual* de hoje.** `daily_slates` permite
  mais de uma linha por data desde a migration 0014 (cadeia de
  correção) — um `slate_id` de rascunho antigo/abandonado passava pela
  checagem antiga (`status = 'rascunho'`) mesmo sem ser o que a página
  de hoje mostra. `_exigir_pode_escrever` agora compara contra
  `buscar_slate_atual(hoje)`, não só o status da linha isolada.
- **HIGH (security-reviewer): resolução de conflito aceitava
  `pick_id` de fora de escopo.** `resolver_conflito_usar_selecao`/
  `resolver_conflito_descartar_todas` mutavam `picks.status` por
  `pick_id` sozinho, sem exigir `status = 'revisao_manual'` nem que a
  fixture pertencesse ao slate — um `pick_id` de qualquer dia/status
  seria forçado pra `vinculado` ou `descartado`. Corrigido: as duas
  funções agora exigem `status = 'revisao_manual' and fixture_id =
  any(fixture_ids_do_slate)`, devolvendo `False`/ignorando
  silenciosamente o que estiver fora de escopo.
- **HIGH (code-reviewer): `editar_piso` não validava contra o piso
  absoluto.** Diferente de `editar_odd_referencia` (que sempre
  recalcula via `calcular_odd_minima`, estruturalmente incapaz de
  ficar abaixo do piso), `editar_piso` gravava `odd_minima` direto — um
  piso digitado errado (ex.: `1.00` com `ODD_MINIMA_ABSOLUTA=1.40`)
  passava sem aviso, porque `bloqueios_de_aprovacao` só comparava
  `odd_referencia`, nunca `odd_minima` em si. Corrigido nas duas
  camadas: `editar_piso` recusa (`PisoAbaixoDoAbsoluto`) na escrita, e
  `bloqueios_de_aprovacao` ganhou a checagem espelhada em `odd_minima`
  como defesa em profundidade.
- **MEDIUM (security-reviewer): `gerar_correcao` sempre carimbava a
  data de "hoje", não a do slate original.** Corrigir um slate
  aprovado antigo faria a correção aparecer como se fosse o rascunho
  de hoje, sombreando o real. Corrigido: a data vem de um `select data
  from daily_slates` no próprio slate substituído.
- **MEDIUM (security-reviewer): checagem de `Origin` falhava aberto
  quando o header vinha ausente.** Só recusava origem *diferente* das
  permitidas; ausência de header passava. Corrigido pra falhar
  fechado — ausência de `Origin` também é recusada (403), validado ao
  vivo com `curl -X POST` sem header.
- **LOW (code-reviewer): hop por `float()` em `editar_odd_referencia`
  antes de `calcular_odd_minima`.** Removido — `Decimal` direto, sem
  round-trip binário (mesma função que já teve um bug real de precisão
  corrigido na Fase 4).

### Resultado rodando contra dado real (2026-08-11)

Console subido de verdade (`uv run python -m scripts.console`) contra o
Postgres de produção, não só `TestClient` com fakes:

- **`GET /saude`**: 200, mostra o estado real do dia (run `degradado`
  por `extracao`, 192 órfãos aguardando partida, cota OddsPapi 15/250
  com projeção 42, `eagle_predict`/`sda` marcados "ok", nenhuma
  assinatura vencendo nos próximos 5 dias — a do operador vence só em
  30 dias).
- **`GET /curadoria`**: 200, aberta (etapa `slate` fechou `ok`) com o
  aviso da extração degradada no topo e "Nenhum item no rascunho de
  hoje" (o único pick vinculado real está `sem_odd`, nunca entrou no
  slate — comportamento correto, não bug).
- **`scripts/build_slate.py` rodado de novo após o novo join com
  `raw_picks`/`sources`**: 0 candidatos, idêntico a antes da mudança —
  confirma que o filtro de quarentena não quebrou a query em produção.
- **`POST` sem header `Origin`**: 403, confirmando o fail-closed ao
  vivo, não só no teste.
- Nenhuma ação de aprovação/remoção foi disparada contra a linha real
  de `daily_slates` de produção nesta sessão — mutar esse estado é
  irreversível e não foi pedido; a lógica de escrita está coberta a
  100% por `FakeCursor`/`TestClient` (ver achados acima, todos
  encontrados e corrigidos antes desta validação).

## Fase 5d — Motor de mensagens + aba Envio (modo manual e modo sessão): concluída

Fecha o console: gera `messages` de verdade a partir de um slate
aprovado (pré-requisito que nunca existiu antes — ver Fase 4, "não gera
`messages` de verdade... falta o que renderizar pra alguém de
verdade") e implementa a aba `/envio`, nos dois modos previstos pelo
documento original (fila manual e sessão guiada com ritmo/atalho
`Enter`). Dividida em quatro sub-fases (A palpite manual + divergência,
B motor de geração, C aba Envio manual, D modo sessão), fechadas com
`code-reviewer`/`security-reviewer` em paralelo sobre o diff inteiro
das quatro juntas — mesmo padrão da Fase 5c, agora sobre uma superfície
maior. 583 testes no projeto (subiu de 454 na Fase 5c).

### Fase A — Palpite manual + alerta de divergência de odds

Duas pendências explícitas deixadas pela Fase 5c: fonte sintética pra
palpite digitado direto na curadoria, e alerta (nunca bloqueio) quando
a odd citada pela fonte diverge muito da odd de referência calculada.

- `migrations/0022_source_console_manual.sql`: semeia
  `sources('console_manual', 'manual', true, false)` — a única exceção
  deliberada à regra "toda fonte nasce em quarentena" (Fase 2): palpite
  digitado pelo próprio operador na curadoria não precisa de período de
  observação, ele já decidiu confiar nele ao digitar.
- `app/console/acoes.py::criar_palpite_manual`: cria `raw_picks` →
  `picks` → `slate_picks` numa função só, porque é a primeira escrita
  do console que **cria** linha em `raw_picks`/`picks`, não só em
  `slate_picks` — risco novo (um pick fantasma que nenhuma outra camada
  jamais validou), mitigado revalidando `fixture_id` contra fixtures
  elegíveis reais no banco (`agendada`, kickoff nas próximas 24h) e
  recusando mercado fora de `MERCADOS_VALIDOS` ou odd abaixo do piso
  absoluto — nunca confia no que o `<select>` do formulário ofereceu.
- `app/console/rules.py::divergencia_relativa`/`tem_alerta_divergencia`:
  `Decimal`, não `float` (mesma convenção da Fase 4), comparando
  `|odd_citada - odd_referencia| / odd_referencia` contra
  `settings.divergencia_odd_alerta_pct` (novo, `0.10`). Alerta visual
  na Curadoria, nunca entra em `bloqueios_de_aprovacao` — é informativo.

### Fase B — Motor de geração de `messages`

- `app/messaging.py` reescrito pra suportar múltiplos palpites por
  mensagem: `ContextoMensagem.palpites` agora é uma tupla de
  `PalpiteNaMensagem` (antes, um só palpite por template), e
  `transmissao=None` omite a linha "Onde assistir" inteira em vez de
  aparecer vazia — `broadcasts`/`broadcast_rules` nunca foram populadas
  por nenhum coletor, então isso é o caminho comum hoje, não o de
  borda.
- `app/messages_generator.py` (novo): motor puro de decisão (quem
  recebe o quê, em que ordem) + funções DB-shape de leitura/escrita.
  Uma mensagem é por `(usuário, fixture, data)` — picks da mesma
  partida se agrupam numa mensagem só (`agrupar_por_fixture`).
  `filtrar_por_preferencia` só **subtrai** do slate completo (critério
  de aceite literal da Fase 4: assinante sem `user_preferences` recebe
  tudo). Idempotência via `idempotency_key` (sha256 de
  `user|fixture|data`, separadores explícitos pra nunca colidir
  `"u1"+"1fix"` com `"u11"+"fix"`) com `ON CONFLICT DO NOTHING`.
- **Decisão de dono da geração:** não é uma 7ª etapa do pipeline
  (`app/pipeline.py`) — acontece dentro da própria transação de
  `post_aprovar_slate` (`app/console/rotas_curadoria.py`), atômico com
  a aprovação. Se a geração falhar, a aprovação também não acontece
  (rollback), em vez de deixar um "aprovado sem mensagem" que ninguém
  percebe. `scripts/generate_messages.py` existe como CLI de
  recuperação manual/futuro scheduler, chamando a mesma função —
  `QUEUE_ENABLED` é checado só dentro de `gerar_mensagens`, único
  choke point, nunca replicado nos três pontos de entrada.
- **Corte de antecedência em dois níveis**, porque o slate aprovado é
  imutável mas a aprovação pode atrasar: nível A na montagem do slate
  (`app/slate.py::instante_de_corte`, soma início da sessão + duração
  estimada da fila + antecedência) e nível B re-checado no momento real
  da geração (`respeita_antecedencia_minima`) — sem o nível B, uma
  aprovação tardia ou uma correção aprovada depois furaria a garantia
  do nível A sozinho.
- Defesa em profundidade repetida da Fase 5c: `gerar_mensagens`
  re-verifica slate aprovado **e** ausência de pick em quarentena no
  momento da geração, não confia só no que a aprovação já checou.

### Fase C — Aba Envio, modo manual

`app/console/rotas_envio.py` (novo): `GET /envio` mostra a fila
(`status='pronta'`, filtro de assinante ativo direto na SQL — mesma
classe do CRITICAL de quarentena da Fase 5c, garantia no dado, nunca só
na tela), agrupada por assinante com link `wa.me` combinado quando há
mais de uma mensagem. `montar_link_whatsapp` usa `quote(corpo,
safe='')` — o default do `urllib.parse.quote` deixa `/` sem escapar, o
que quebraria o parsing da URL num corpo com data/placar.
`marcar_enviada`/`pular` são idempotentes via `WHERE status =
'pronta' ... RETURNING id`, nunca `cur.rowcount`.

### Fase D — Modo sessão

Fluxo guiado: um assinante por vez, em ordem justa e rotativa entre
dias (`app.messages_generator.ordem_da_sessao`, já existente desde a
Fase B), com iniciar/pausar/retomar/encerrar.

**Achado de design central, pego ainda no plano, antes de escrever
código:** calcular a ordem sobre "quem ainda tem mensagem pendente"
reembaralharia a fila a cada mensagem resolvida — `n` diminui, o
offset de `ordem_da_sessao` muda, e quem seria a próxima parada pula
pro fim. Corrigido calculando a ordem sobre um **universo estável do
dia** (`app/console/queries.py::universo_da_sessao` — todo assinante
ativo que teve mensagem gerada hoje, em qualquer status, via
`status='pronta' or slate_id in (slates da mesma data)`), com a fila
real só filtrando esse universo, nunca substituindo-o. Teste de
regressão nomeado (`test_montar_paradas_marcar_uma_como_resolvida_
nao_muda_posicao_das_outras`) trava esse comportamento.

Decisões de produto tomadas com o PM nesta sessão (D13–D19, numeração
seguindo D1–D12 já implementados nas sub-fases A/B/C):

- **D13 — sessão abandonada.** Nunca expira por relógio/inatividade,
  mas se a fila do dia zerar (todo mundo enviado/pulado/expirado), a
  sessão se auto-encerra (`motivo_encerramento='fila_vazia'`,
  `encerrada_por='sistema'`) na próxima abertura de `/envio/sessao` —
  encerramento honesto, não abandono. Validado ao vivo (ver abaixo).
- **D14 — pausa é funcional, mas estreita.** Bloqueia só o caminho
  `modo=sessao` das rotas de mensagem (409 se a sessão estiver
  `pausada`); o modo manual (`/envio` sem o campo `modo`) nunca é
  afetado, mesmo com uma sessão pausada existindo.
- **D15 — "Pular" continua terminal, sem verbo "adiar" novo.** Mesma
  semântica de sempre (sai da fila pra sempre, com motivo) — não haverá
  um segundo verbo "pula a vez, tenta de novo depois" por ora.
- **D16 — slate corrigido no meio de uma sessão em andamento.** Aviso
  visual na tela (`aviso_slate_mudou`, comparando
  `sessao.slate_id` contra o slate atual), a sessão não se encerra
  automaticamente — decisão fica com o operador.
- **D17 — sem trava de horário; permite 2ª sessão no mesmo dia.**
  `envio_sessoes` usa índice único **parcial** (`where encerrada_em is
  null`), não `unique(data)` puro — mesmo erro já corrigido em
  `daily_slates` na migration 0014.
- **D18 — resumo da sessão é só tela, derivado de `messages`.** Nenhuma
  tabela nova pra congelar números — revisitar só quando o relatório
  diário da Fase 7 existir de verdade e precisar de um valor
  congelado no momento do encerramento.
- **D19 — confirmado: quem "perde a vez" por expiração ainda ocupa a
  posição dele na rotação do dia.** Consequência aceita e desejada do
  universo estável (achado central acima) — a rotação existe pra não
  deixar sempre a mesma pessoa por último, e uma mensagem expirar não é
  culpa da ordem.

`migrations/0021_envio_sessoes.sql`: tabela **sem `user_id`**, por
design — a sessão é metadado de operação do console, não de assinante;
com `user_id` ela precisaria entrar em `EXPORT_TABELAS`
(`app/users.py`, guard de cobertura LGPD) descrevendo algo que não é o
assinante, e pior, um campo tipo `parada_atual_user_id` seria
exatamente o ponteiro persistido que a reentrância (recarregar a
página no meio de uma sessão continua de onde estava, sem estado em
memória) proíbe.

`app/console/static/sessao.js`: **primeiro JavaScript do projeto**.
Cosmético por design — contagem regressiva do intervalo entre envios
(persistida só como timestamp epoch em `sessionStorage`, nunca
telefone/nome/corpo/id) e atalho `Enter` pra marcar como enviada (que
nunca rouba o `Enter` de dentro do campo `motivo` do "Pular", os dois
formulários compartilham o mesmo card). Sem `fetch`/XHR em lugar
nenhum — toda mutação real continua um `<form method="post">` nativo,
preservando o header `Origin` que `checar_origin` exige. Botão
renderizado **habilitado** pelo servidor; é o JS que desabilita
durante a contagem — se o script falhar ou for desabilitado no
navegador, a página continua 100% operável.

### Revisão: 1 HIGH real (pré-existente, achado só agora) + 1 MEDIUM + 1 LOW, todos corrigidos

`code-reviewer` e `security-reviewer` rodados em paralelo sobre o diff
inteiro da Fase 5d (A–D). Security review veio limpo — 0 CRITICAL/HIGH,
os 9 vetores específicos pedidos (vazamento de PII em log/exceção, XSS
via corpo de mensagem, open redirect no campo `modo`, cobertura de
`checar_origin`, IDOR em `sessao_id`/`fixture_id`, SQL injection,
`sessao.js` sem fetch/XHR, `sessionStorage` só com epoch,
`uuid.UUID`/`str`) todos confirmados OK por leitura direta do código,
não por suposição.

- **HIGH (code-reviewer): botão "usar esta seleção" na resolução de
  conflito submetia um `ordem` sem relação com o slate real.**
  `curadoria.html` calculava `{{ loop.length + 1 }}` dentro do loop
  sobre `grupo` — a lista de candidatos em conflito **daquela
  fixture+mercado** (quase sempre 2), não o slate inteiro. O valor
  submetido (quase sempre `3`) colidia com `ordem` já existente em
  `slate_picks` (sem `unique(slate_id, ordem)` pra pegar isso — só
  `unique(slate_id, pick_id)`), o que quebra silenciosamente
  `reordenar_item` (assume no máximo uma linha por `ordem`) e enviesa
  `aplicar_max_msgs_dia`/`GrupoFixture.prioridade`
  (`app/messages_generator.py`), que decidem qual pick cortar quando um
  assinante tem `max_msgs_dia`. Bug pré-existente da Fase 5c, só
  descoberto agora porque nenhum teste renderizava o template de
  verdade. Corrigido: `ordem` sai do form inteiramente,
  `resolver_conflito_usar_selecao` (`app/console/acoes.py`) calcula
  `coalesce(max(ordem), 0) + 1` server-side, mesmo padrão já usado em
  `criar_palpite_manual`.
- **MEDIUM (code-reviewer): `RelatorioGeracao.pulados_preferencia`
  existia na dataclass mas nunca era incrementado.** Sem impacto real
  em dado de produção hoje (`user_preferences` não tem caminho de
  escrita ainda), mas o campo mentiria (sempre `0`) assim que a UI de
  preferências existir. Corrigido: `gerar_mensagens` agora mede, por
  assinante, quantos grupos de fixture desapareceriam com a preferência
  aplicada frente ao slate sem filtro nenhum, e soma isso ao contador.
- **LOW (code-reviewer): comparação de `odd_min`/`odd_max` em
  `filtrar_por_preferencia` usava `float` puro na fronteira**, contra a
  convenção do projeto (`Decimal`, firmada depois de um bug real de
  precisão na Fase 4). Sem bug observável hoje (é uma comparação
  direta, sem aritmética extra que perderia precisão) — corrigido por
  consistência preventiva antes da UI de preferências existir.

### Validação ao vivo (2026-08-11)

Console subido contra o Postgres de produção, fluxo de sessão completo
de ponta a ponta, sem dado sintético — a mensagem usada já existia de
uma validação anterior (palpite manual real do próprio operador,
Avaí x CRB):

- `POST /envio/sessao/iniciar` → `303`, sessão real criada
  (`51abbe74-...`), `GET /envio/sessao` mostrando a parada em foco
  (`PM (+5547996894342)`, "parada 1 de 1"), corpo renderizado correto,
  link `wa.me` com acento/emoji/pontuação corretamente codificados
  (confirmado por inspeção, nunca clicado — abrir um `wa.me` real
  dispara uma ação de compose de verdade no WhatsApp).
- `POST .../pausar` → `303`; tentativa de marcar como enviada com
  `modo=sessao` enquanto pausada → `409 {"detail":"sessao de envio
  esta pausada"}` (D14 confirmado); `POST .../retomar` → `303`.
- `POST /envio/{id}/enviada` com `modo=sessao` → `303`; a fila zerou e
  a sessão se auto-encerrou na mesma requisição (D13 confirmado) — a
  tela seguinte mostrou "Sessão concluída, Enviadas: 1" e "Nenhuma
  sessão de envio aberta hoje". Confirmado direto no Postgres:
  `envio_sessoes.status='encerrada'`, `encerrada_por='sistema'`,
  `motivo_encerramento='fila_vazia'`; `messages.status='enviada'` com
  timestamp real.
- Suíte completa (583 testes) reconfirmada depois de cada correção de
  revisão, cobertura 100% em `app/console/{rules,queries,acoes}.py` e
  em `app/console/rotas_envio.py` (a convenção do projeto aceita
  <100% em rotas quando o resto é I/O de conexão — `rotas_curadoria.py`
  está em 93%, mas `rotas_envio.py` chegou a 100% depois de remover
  uma checagem que se provou código morto: `avaliar_acesso_envio`
  já garante `slate_status == "aprovado"` sempre que libera, então uma
  segunda checagem idêntica em `post_iniciar_sessao` nunca era
  alcançável).
- **Pendência documentada, não esquecida:** o checklist interativo de
  navegador do `sessao.js` (contagem regressiva rodando/liberando,
  atalho `Enter` marcando como enviada, `Enter` dentro do campo
  `motivo` **não** marcando, reentrância real após F5) não foi
  exercido num browser real nesta sessão — a única mensagem `pronta`
  real disponível foi consumida pela validação do fluxo de
  sessão/auto-encerramento acima, e fabricar mais dado sintético
  (outro palpite manual + correção de slate) só para esse teste
  cosmético não pareceu proporcional, já que os dois revisores leram o
  arquivo inteiro e confirmaram a lógica (sem `fetch`/XHR, sem dado
  pessoal em `sessionStorage`, guarda correta contra roubar `Enter` do
  campo de motivo). Vale rodar esse checklist manualmente na primeira
  sessão real de envio do produto.

## Fase 6a — Motor de liquidação: concluída (escopo central)

Começada numa sessão anterior sem registro neste documento (achado ao
retomar o projeto: `app/settlement/linhas.py` já existia, testado; ver
"Retomada" abaixo). Fechados nesta sessão: `app/settlement/selecao.py`
(estava sem nenhum teste) e `app/settlement/engine.py` (motor de
dispatch por mercado, não existia — inclui os seis resolvers que dependem
só de placar/`fixture_stats`: 1x2, ambas_marcam, over_under, handicap,
escanteios, cartões) e a persistência da liquidação (`pick_results` +
CLIs de execução/revisão manual, ver seção própria abaixo). 781 testes
no projeto (subiu de 632). Escopo central fechado; pendências menores
(parser de "cartões por time", uso auxiliar do OddsPapi, alerta de 15%)
ficam documentadas ao final, junto das pendências de 6b/6c.

### Retomada: achado real ao analisar a pasta antes de continuar

Antes de escrever qualquer linha nova, uma varredura do diretório (pedida
explicitamente pelo usuário: "analise a pasta e continue de onde parou")
achou `app/settlement/` já criado fora desta conversa, com os arquivos
datados de horas antes do início desta sessão. `linhas.py` (kernel de
linha quebrada .25/.75, ver `combinar`/`dividir_linha`) estava completo
e 100% coberto por `tests/test_settlement_linhas.py`. `selecao.py`
(parser de `picks.selecao` texto-livre pra intenção tipada) estava
escrito mas **sem nenhum teste** — pelos timestamps dos arquivos, foi
exatamente aí que a sessão anterior parou. Decisão tomada com o
usuário: testar `selecao.py` primeiro (TDD retroativo) e seguir
construindo `engine.py` até fechar o que desse nesta sessão.

### `app/settlement/selecao.py`: 49 testes novos + 1 bug real achado por eles

O bug: o parser de DNB (`parse_1x2_ou_variantes`) comparava o nome do
time contra a **frase inteira** pra decidir de qual time era o DNB. Mas
o formato real da fonte é "X para ganhar ou empatar contra Y" — os
**dois** nomes de time sempre aparecem na frase, então a checagem contra
a string inteira nunca conseguiria diferenciar qual é o sujeito da
aposta (os dois sempre "batiam"). Corrigido restringindo a checagem ao
trecho de texto **antes** do marcador DNB (`_MARCADORES_DNB`, novo:
"ganhar ou empatar"/"dnb"/"draw no bet"/"empate anula") — o adversário,
quando existe, sempre vem depois de "contra", então já fica fora do
segmento checado. Mesma classe de cautela já estabelecida em
`app.matcher`/`app.odds_resolution`: nunca chutar quando a evidência é
ambígua.

### `app/settlement/engine.py`: motor de dispatch por mercado, novo

`Resolution(resultado, evidencia)` — deliberadamente **sem** um campo de
retorno financeiro (`fator_retorno`), apesar do documento original
sugerir que `Resolution` carregaria isso também. Decisão desta sessão:
o cálculo de banca (Fase 6b, ainda não construída) depende de
`odd_minima` do pick, que é uma preocupação de dinheiro/aposta, não de
"o que aconteceu no jogo" — misturar as duas no mesmo objeto acopla um
módulo que ainda não existe a este. Revisitar se a Fase 6b mostrar que
essa separação foi um erro.

Mercados resolvidos nesta entrega (todos os que dependem só de
`placar_casa`/`placar_fora`, nenhum de `fixture_stats`):

- **1x2** — inclui dupla chance (`1X`/`X2`/`12`) e DNB, porque a
  extração da Fase 3 sempre grava `mercado="1x2"` pra essas variantes;
  só o texto de `selecao` distingue. DNB empata → `void`.
- **ambas_marcam** — compara `IntencaoAmbasMarcam.sim` contra
  `placar_casa>0 and placar_fora>0`.
- **over_under** (gols) — usa o kernel de linha quebrada de `linhas.py`
  pra `.25`/`.75` (linha inteira tem void na batida exata, `.5` nunca
  empata). 58 testes no engine cobrem cada quarto de linha entre 0.25 e
  4.75, pedido explícito da spec.
- **handicap** (europeu e asiático) — mesmo kernel, `diferenca = margem
  + linha` do lado apostado. Push exato na linha inteira, meio-green/
  meio-red nas quebradas.

`picks.linha` (coluna que existe desde a Fase 0 mas a extração nunca
populou — ver docstring de `selecao.py`) tem prioridade sobre a linha
extraída do texto quando presente (`_linha_efetiva`), pensando na
entrada manual via console que ainda vai escrever essa coluna.

Regra de ouro mantida em todo o motor: dado ambíguo ou malformado nunca
vira `red`/`green` por suposição — vira `nao_liquidavel`, com motivo na
evidência. Partida `adiada`/`cancelada` é `void` incondicional, antes de
qualquer resolver rodar.

### Revisão do `code-reviewer`: 1 HIGH real + 1 MEDIUM + 2 LOW, todos corrigidos

- **HIGH:** `parse_total`/`parse_handicap` não tinham a mesma guarda de
  "fora de escopo" (`_fora_de_escopo`, já existente em
  `parse_1x2_ou_variantes` desde antes desta sessão, pra frases como "1º
  tempo"/"prorrogação"/"agregado") — uma seleção real do tipo "Mais de
  0.5 gols no 1º tempo" seria liquidada **contra o placar do jogo
  inteiro**, produzindo um `green` silenciosamente errado pra uma aposta
  de escopo diferente (quase qualquer partida encerrada tem ≥1 gol no
  total). Corrigido chamando `_fora_de_escopo` no topo dos dois parsers,
  mesma guarda que `parse_1x2_ou_variantes` já usa. Teste de regressão
  pros dois parsers.
- **MEDIUM:** `liquidar()` só tratava `adiada`/`cancelada` como void
  incondicional — qualquer outro status (`agendada`, `ao_vivo`) com
  placar não-nulo passaria direto pro resolver de mercado. Hoje isso
  não é alcançável na prática (`collect_results.py`, Fase 1f, só grava
  placar quando o status já resolveu pra `encerrada`), mas essa é uma
  garantia de **outro** módulo — `engine.py` não devia confiar nela
  implicitamente. Corrigido: `liquidar()` agora exige
  `status == "encerrada"` (além de já não estar em
  `_STATUS_VOID_INCONDICIONAL`), mesmo padrão de defesa em profundidade
  já usado em `app.pipeline.avancar_etapas` e na Fase 5c.
- **LOW:** o tipo `Resultado` (`Literal["green", "meio_green", "void",
  "meio_red", "red", "nao_liquidavel"]`) estava duplicado
  palavra-por-palavra em `linhas.py` e `engine.py` — mesma classe de
  risco de drift já corrigida pra `upsert_source` na revisão holística
  pós-Fase 2. Corrigido: definido uma vez em `linhas.py`, importado em
  `engine.py`.
- **LOW (gap de teste):** faltava um teste de `_linha_efetiva` (prioridade
  de `picks.linha` sobre o texto) especificamente pro resolver de
  handicap — só existia pro de over/under, mesmo helper. Adicionado.

### Resolvers de escanteios e cartões (fixture_stats), mesma sessão

Pedido explícito do usuário logo depois de fechar os quatro primeiros
resolvers ("segue pra escanteios e cartões usando fixture_stats").
`FixtureStatTime` (novo dataclass — `escanteios`, `cartoes_amarelos`,
`cartoes_vermelhos`, sem identidade de time porque nenhum resolver desta
entrega distingue por time) + `_resolver_escanteios`/`_resolver_cartoes`,
reaproveitando o mesmo kernel de linha quebrada de `linhas.py`. Todos os
quatro resolvers pré-existentes (1x2, ambas_marcam, over_under, handicap)
ganharam um terceiro parâmetro `stats` não usado, só pra manter o
dispatch de `REGISTRO`/`liquidar()` uniforme — nenhuma lógica interna
deles mudou.

Duas decisões registradas, não confirmadas contra dado real:

- **`cartões` = amarelo + vermelho somados** por time (`_cartoes_do_time`).
  Convenção não verificada contra documentação de casa de aposta —
  parece bater com o mercado "Bookings" do OddsPapi (Fase 1b), mas
  revisitar quando a conferência amostral (pendência #3 abaixo) rodar
  de verdade.
- **`eh_condicao_por_time`** (novo em `selecao.py`): mercado "cartões,
  condição por time" (spec) é distinto de total de cartões — a aposta
  exige que os **dois** times batam a condição individualmente (ex.:
  "Ambas as equipes recebem 2 cartões ou mais"), não a soma. Sem nenhum
  exemplo real desse texto nos dados já coletados (só o total, tipo
  "Mais de 4,5 cartões mostrados", apareceu de verdade) — escrever o
  parser completo agora seria resolver especulativamente, o que o
  projeto evita desde a Fase 1c. Só o marcador é reconhecido, pra
  desviar pra `nao_liquidavel` antes do resolver de total tentar
  liquidar por engano.

### Revisão do `code-reviewer` (2ª rodada): 2 MEDIUM corrigidos, 1 risco residual documentado

- **MEDIUM:** `_soma_stat` aceitava `len(stats) < 2` como guarda de
  cobertura, mas não rejeitava `len(stats) > 2` — sem identidade de time
  no dataclass, mais de duas linhas (fan-out de join, duplicata de time)
  seriam somadas como se fossem um total válido. Corrigido pra
  `!= 2`. Teste de regressão.
- **MEDIUM, aceito como risco documentado, não corrigido por código:**
  `eh_condicao_por_time` falha "inseguro" — uma frase real de condição
  por time que não bata com nenhum dos 5 marcadores hardcoded (ex.:
  "Os 2 times recebem cartão", sem usar "ambas"/"cada"/"os dois")
  cairia direto no parser de total e poderia ser liquidada como se fosse
  aposta no total da partida, um mercado diferente. Decisão desta sessão:
  **não** expandir a lista de marcadores especulativamente (arriscaria
  trocar um falso-negativo por um falso-positivo igualmente não
  validado) — mesma cautela já aplicada ao resto do parser. Registrado
  aqui como risco residual explícito, não como pendência silenciosa:
  revisitar a lista de marcadores assim que uma seleção real de
  "cartões por time" aparecer nos dados coletados.

### Persistência da liquidação + CLI de revisão manual, mesma sessão — com um erro real corrigido a tempo

Pedido do usuário: "continue" (implicitamente, fechar as pendências
óbvias da Fase 6a). Construído: `app/settlement/persistencia.py`
(camada DB-shape) + dois scripts (`scripts/liquidar_picks.py`, roda o
motor automaticamente; `scripts/liquidacao.py`, CLI `listar`/`marcar`
pra revisão manual — renomeado de `python -m app.settlement review`,
mesma decisão D1 já tomada pra `scripts/users.py`/`scripts/subs.py`:
lógica de negócio/CLI fica em `scripts/`, não em `app/`). 781 testes no
projeto.

**Erro real cometido e corrigido antes de fechar, achado pelo
`code-reviewer`:** a primeira versão criou uma tabela nova,
`pick_liquidacoes` (migration 0023), sem checar se o schema já tinha
algo pra esse papel. Tinha — `pick_results` existe desde a Fase 0
(`migrations/0001_init.sql`) e **já estava em uso** pela métrica
"encerradas sem liquidação" do console (`app.console.queries.
encerradas_sem_liquidacao`, Fase 5c, com teste próprio desde então). Se
não tivesse sido pego, `scripts/liquidar_picks.py` teria começado a
gravar liquidações numa tabela que o dashboard **nunca olha** — o
contador de backlog do `/saude` ficaria preso pra sempre, mentindo
silenciosamente pro operador. Corrigido com uma migration nova
(`0024_drop_pick_liquidacoes.sql`, revertendo a 0023 — mesmo tratamento
já dado ao erro de `unique(data)` em `daily_slates`, Fase 4: migration
corretiva nova, nunca editar uma já aplicada) e `persistencia.py`
reescrito pra ler/gravar em `pick_results`.

Essa correção também mudou um design: `pick_results.resultado` já
aceitava `'nao_liquidavel'` no CHECK desde a Fase 0 (diferente do que a
`pick_liquidacoes` descartada assumia) — então agora **todo** pick
tentado ganha uma linha, mesmo quando o resultado é `nao_liquidavel`.
Isso é o que faz `encerradas_sem_liquidacao` (mede "o pipeline ainda nem
tentou") e a fila de revisão manual (mede "tentou, ficou ambíguo, ninguém
revisou": `pick_results.resultado = 'nao_liquidavel' and
revisado_por_humano = false`) serem dois sinais diferentes que não se
confundem, em vez de reinventar um terceiro.

**Segundo achado do `code-reviewer`, também corrigido:** `scripts/
liquidacao.py marcar` buscava `picks.fixture_id` sem checar se vinha
`NULL` (pick ainda não vinculado) — `str(None)` virava a string literal
`"None"`, que quebrava com um `InvalidTextRepresentation` cru do driver
no cast `::uuid` seguinte. Mesma classe de bug já corrigida duas vezes
na Fase 5b (`ReferenciaPagamentoDuplicada`, `uuid_arg`). Corrigido com
`inner join` contra `fixtures` (pick sem fixture some da consulta, vira
"não encontrado" em vez de `None` disfarçado) e validação explícita de
`status == 'vinculado'`/`'encerrada'` antes de aceitar a marcação manual
— sem isso, um `pick_id` de status/fixture errado seria forçado pra
`pick_results` sem nenhum aviso.

Rodado ao vivo contra o Postgres real (0 fixtures encerradas ainda, sem
dado real pra validar ponta a ponta — mesma limitação já documentada em
fases anteriores): os dois scripts executam sem erro, e
`encerradas_sem_liquidacao` segue funcionando exatamente como antes.

Observação registrada (não bloqueante): a aba `/saude` ainda não mostra
a contagem de `nao_liquidavel` pendente de revisão — só visível via
`scripts/liquidacao.py listar`. Fica pra um passe futuro no console.

### Pendências explícitas da Fase 6a (não é conclusão da fase)

1. Parser completo de "cartões, condição por time" — só o marcador de
   detecção existe (ver acima); falta o exemplo real de texto pra
   escrever e validar o parser em si.
2. Uso auxiliar do `/settlements` do OddsPapi (conferência amostral +
   saída pra mercado sem resolver) — não existe. Também serviria pra
   confirmar a convenção `cartões = amarelo + vermelho` acima.
3. Alerta de "`nao_liquidavel` passou de 15% dos palpites de uma fonte"
   (spec) — não implementado; não existe canal de alerta no projeto
   ainda, e não fazia sentido construir um só pra isso.
4. Contagem de pendentes de revisão manual não aparece no console
   `/saude` ainda (ver acima) — só via CLI.

## Fase 6b — Simulação de banca: concluída (escopo central)

Pedido do usuário: "continue pra Fase 6b". Construído nesta sessão:
`app/settlement/banca.py` (cálculo puro — fator de retorno, ordenação
determinística, replay fixo/proporcional, filtro por período de
assinatura), migration `master_ledger` (extrato mestre) +
`app/settlement/master_ledger.py` (reconstrói do zero a cada rodada a
partir de `pick_results` + `slate_picks`/`daily_slates` + `messages`,
aplicando o critério "entra no extrato": slate aprovado + enviado a pelo
menos um assinante + antes do kickoff), `app/settlement/
extrato_usuario.py` (recorte por usuário, gravado em `bets`), e dois
CLIs (`scripts/build_master_ledger.py`, `scripts/build_bets.py`). 836
testes no projeto (subiu de 810).

### Tensão real no documento original, resolvida com evidência do próprio projeto

A seção 6b do documento diz explicitamente "não duplique o extrato
mestre 200 vezes no banco" e descreve o extrato do usuário como
"calculado sob demanda a partir do `master_ledger`" — sem tabela
própria. Mas o schema já criado desde a **Fase 0** (`migrations/
0001_init.sql`) tem uma tabela `bets` inteira, com comentário próprio
("Banca simulada: um extrato por usuário, append-only... Regra de ouro
do extrato: `bets` é append-only e a banca atual é sempre recalculada
do início, nunca lida de um campo mutável"), e a Fase 5b já a
referenciava em `app.users.EXPORT_TABELAS` (LGPD) com um comentário
próprio ("pra a Fase 6 (master_ledger etc.) nao esquecer isso
silenciosamente"). Ou seja: a intenção de ter `bets` populada por
usuário nunca foi abandonada, só não foi reconciliada com a prosa mais
detalhada escrita depois para a seção 6b.

**Resolução adotada:** as duas coisas não competem. `master_ledger`
centraliza o FATO da liquidação (resultado, odd publicada, fator) uma
vez só — isso é o que "não duplicar" realmente protege. `bets`
materializa a PROJEÇÃO de cada usuário sobre esse fato — stake e banca
são inerentemente pessoais (`banca_inicial`/`stake_pct`/`modo_stake`
variam por usuário via `user_bankroll_config`, também já existente
desde a Fase 0 e sem nenhum fluxo que a popule ainda — `buscar_config_
banca` cai pro default de `app.config` quando não há linha). Não é
duplicação, é o ponto da tabela.

### Odd usada no cálculo: `slate_picks.odd_minima`, não `picks.odd_minima`

"A decisão mais importante da fase" (spec): o extrato assume que a
aposta foi feita na odd mínima **publicada**, nunca na de referência
nem na citada pelo tipster. `master_ledger.odd` vem da cópia congelada
em `slate_picks.odd_minima` (Fase 4: "slate aprovado é imutável"), não
de `picks.odd_minima` — que em teoria pode mudar depois via console.

### Revisão do `code-reviewer`: 1 CRITICAL real + 1 MEDIUM, ambos corrigidos

- **CRITICAL:** a query de elegibilidade do `master_ledger` filtrava só
  `daily_slates.status = 'aprovado'` — mas `daily_slates` não tem status
  "substituído": uma correção (migration 0014, `app.console.acoes::
  gerar_correcao`) cria um slate NOVO, e o antigo fica `aprovado` **pra
  sempre** (mesmo princípio "slate aprovado é imutável"). Sem filtrar
  pelo mais recente, um pick removido ou reprecificado numa correção
  continuaria contando pelo slate velho — ou, se o mesmo pick_id
  aparecesse nos dois slates aprovados, o `insert` violaria o
  `unique(pick_id)` do `master_ledger` e **derrubaria a reconstrução
  inteira**. Corrigido com o mesmo padrão já usado em `app.daily_slates.
  buscar_slate_atual` (mais recente por `criado_em`), restrito a
  `status = 'aprovado'`. Achado real de uma tensão entre duas features
  já existentes (Fase 4/5c) que nunca tinham sido combinadas antes.
- **MEDIUM:** `filtrar_por_periodos_assinatura` comparava
  `kickoff_utc.date()` em UTC direto contra `subscriptions.inicio`/`fim`
  (datas de calendário do Brasil) — um kickoff às 22h BRT (comum no
  futebol brasileiro) já é 01h UTC do dia seguinte, então uma entrada
  na borda de início/fim de assinatura podia entrar ou sair errado.
  Corrigido convertendo pro fuso `America/Sao_Paulo` antes do `.date()`,
  mesmo padrão já usado em `app.pipeline.data_operacional`.

Rodado ao vivo contra o Postgres real (0 entradas — nenhum pick
publicado+enviado+liquidado ainda, esperado dado o volume atual): os
dois CLIs executam sem erro.

## Fase 6c — Métricas por usuário: concluída (escopo central)

Pedido do usuário: "continue pra Fase 6c". `app/settlement/metricas.py`
(cálculo puro sobre o histórico de apostas de um usuário: banca atual,
variação, total apostado, lucro, ROI, taxa de acerto, odd média,
drawdown máximo + tempo de recuperação, sequência atual, não-liquidados
no período) + `app/settlement/relatorio_usuario.py` (DB-shape, lê
`bets`/`pick_results`) + `scripts/relatorio.py` (`usuario --periodo
7d|30d|tudo`). 836 testes no projeto.

Decisões desta sessão, documentadas no docstring do módulo (sem
confirmação do PM): taxa de acerto exclui `void` do numerador e do
denominador (convenção padrão de mercado de apostas — só "meio-green
como 0,5" é literal da spec); drawdown máximo em R$ absoluto, não
percentual; sequência atual generaliza pra qualquer resultado repetido,
não só green/red.

**Regra dura da spec cumprida:** `nao_liquidados_no_periodo` é sempre
calculado e sempre impresso na mesma linha do ROI (`scripts/
relatorio.py`) — nunca um sem o outro, exatamente como a seção 6c exige
("o número está viesado e você não sabe pra que lado").

### Revisão do `code-reviewer`: 1 MEDIUM corrigido

`sequencia_atual` estava recortada pelo período pedido (`--periodo 7d`
só olhava as apostas dentro da janela) — diferente de `banca_atual`, que
o próprio módulo já documentava como deliberadamente global. Uma
sequência real de 10 greens, com só 3 dentro da janela de 7 dias,
mostraria "3x green" — número plausível e errado. Corrigido pra usar o
histórico completo (`todas_apostas`), mesmo raciocínio de `banca_atual`:
sequência é estado do "agora", não um fluxo dentro da janela.

Rodado ao vivo contra o Postgres real (`python -m scripts.relatorio
usuario --user-id ... --periodo tudo`): banca R$ 1000 (default, sem
`user_bankroll_config` própria), 0 apostas — consistente com
`master_ledger`/`bets` ainda vazios.

## Fase 6d — Performance por fonte: concluída (escopo central)

Pedido do usuário: "vai pra Fase 6d". Escopo maior que 6a-6c: TODOS os
picks liquidados, publicados ou não — inclui fontes em quarentena,
picks cortados por conflito e picks rejeitados pelo piso de odd.
`app/settlement/performance_fonte.py` (agregação pura por grupo:
volume liquidado/não-liquidado/sem_odd, percentual não-liquidados, ROI
com stake unitário, taxa de acerto — reaproveitando `calcular_taxa_acerto`,
extraída pra `banca.py` nesta sessão pra não duplicar entre 6c e 6d —,
odd média, diferença média odd citada vs. referência, e sugestões de
desativação/promoção) + `app/settlement/relatorio_fonte.py` (DB-shape,
três quebras: por fonte, por fonte+mercado, por fonte+tipster) +
`scripts/relatorio.py fontes --days 30`. 868 testes no projeto.

### Lacuna real exposta pela própria Fase 6d, corrigida em código já em produção (Fase 4)

A spec explica: "Cada um deles tem odd de referência e odd mínima
sombra, capturadas na coleta, então o ROI é calculável para todos —
essa é a razão de ter movido a captura da odd para lá." Investigando o
que isso exigia, achei que `scripts/resolve_odds.py` (Fase 4, já em
produção) **nunca gravava `picks.odd_referencia`/`odd_minima`** quando
um pick era rejeitado pelo piso (`odd abaixo de ODD_MINIMA_ABSOLUTA`) —
só registrava o valor em texto livre no motivo do órfão. Sem isso, um
pick descartado pelo piso nunca teria dado com que a Fase 6d pudesse
calcular ROI. Corrigido: o branch "abaixo do piso" agora grava a odd
sombra antes de marcar `descartado`, igual ao branch de sucesso.

Consequência de layering: `app/settlement/persistencia.py` (Fase 6a)
também precisou ampliar `buscar_picks_pendentes` de `status =
'vinculado'` pra `status in ('vinculado', 'descartado')` — picks
cortados por conflito ou rejeitados pelo piso agora liquidam em
`pick_results` também. Confirmado que isso **não** afeta a métrica
`encerradas_sem_liquidacao` do console (Fase 5c, continua só
`vinculado`, semântica de "backlog do operador" deliberadamente
diferente de "tudo pra analytics") nem vaza pro `master_ledger` (Fase
6b, que só conta o que foi de fato aprovado+enviado — picks
`descartado` nunca chegam em `slate_picks` de um slate aprovado atual).

### Revisão do `code-reviewer`: 1 MEDIUM, resolvido com documentação (não com troca de fórmula)

`calcular_odd_minima` aplicada a uma odd já abaixo do piso **sempre**
devolve exatamente `ODD_MINIMA_ABSOLUTA` (o `max(...)` nunca escolhe o
outro lado) — todo pick rejeitado pelo piso mostra a mesma odd sombra,
não importa o quão longe da odd real de mercado ele estava. Não é um
bug de cálculo: é a "mesma fórmula de piso pra todo mundo" (regra de
comparabilidade da spec) respondendo literalmente "se esse pick tivesse
batido exatamente o nosso piso, seria lucro?" — nunca tentando
reconstruir a odd real de um pick que nunca foi oferecido a ninguém.
Trocar pra `odd_referencia` só nesse caso quebraria a comparabilidade
de outro jeito (base diferente conforme o motivo de exclusão). Resolvido
documentando o comportamento explicitamente em `resolve_odds.py` e no
docstring de `performance_fonte.py`, pra ninguém confundir esse número
com odd de mercado real ao comparar fontes.

Rodado ao vivo contra o Postgres real (`python -m scripts.relatorio
fontes --days 30`): "nenhum dado no período" nas três quebras — esperado,
0 fixtures encerradas hoje.

## Fase 6e — Mensagem de resultado: concluída (fechamento do palpite + resumo semanal)

Pedido do usuário: "vai pra Fase 6e". A spec descreve dois formatos
novos de mensagem — "fechamento do palpite" (algumas horas após o jogo)
e "resumo semanal" (sem fixture, agregado da semana). Antes de codar,
achei uma tensão real de schema: `messages.fixture_id` é `not null`, e
a fila de envio inteira (`app.console.queries.fila_envio`,
`contadores_do_dia`, os templates `envio.html`/`envio_sessao.html`, o
fluxo de sessão) faz `inner join` com `fixtures` — mexer nisso pra
suportar mensagem sem partida tocaria bastante código já em produção
da Fase 5d.

**Decisão tomada com o usuário (pergunta feita antes de codar):**
construir só "fechamento do palpite" nesta sessão, com resumo semanal
adiado como pendência explícita e documentada — não meio-construído
de forma invisível. Confirmado pelo `code-reviewer` depois: a fila de
envio realmente faz `INNER JOIN` com `fixtures`, então uma mensagem sem
fixture ficaria invisível pra sempre na fila se eu tivesse forçado o
schema a aceitar `fixture_id` nulo sem reescrever esse código.

### O que foi construído

`migrations/0026_messages_tipo.sql` (`messages.tipo`, default
`'palpite'`, agora aceita `'fechamento'` também — `'resumo_semanal'`
fica de fora de propósito, ver acima) + `app/messaging.py` (template
`renderizar_fechamento`, com as 4 regras obrigatórias da spec: "banca
simulada" é texto literal do template, nunca uma variável que alguém
poderia esquecer de qualificar; nenhuma linguagem de projeção/previsão;
resultado sempre identificado com a partida que cobre; rodapé legal
obrigatório, mesma checagem de `renderizar_mensagem`) +
`app/fechamento_generator.py` (lê `bets` — Fase 6b, extrato já
calculado por usuário — agrupa por usuário+fixture, gera mensagem) +
`scripts/gerar_fechamentos.py`. 893 testes no projeto.

**Idempotência:** chave própria (`montar_idempotency_key_fechamento`,
prefixo `"fechamento|"`), não uma modificação da função já em produção
usada pelas mensagens de palpite — mais seguro que alterar o formato de
hash de algo que dado real já depende, e garante que as duas nunca
colidem pra mesma (usuário, fixture, data).

### Revisão do `code-reviewer`: 1 CRITICAL real + 1 HIGH real + 2 MEDIUM, todos corrigidos ou documentados

- **CRITICAL:** `app.messages_generator.expirar_mensagens_vencidas`
  marcava **qualquer** mensagem `'pronta'` como `'expirada'` assim que
  o kickoff da fixture já tivesse passado — sem filtro de `tipo`. Como
  uma mensagem de fechamento **sempre** aponta pra um jogo que já
  aconteceu (essa é a premissa inteira do recurso), ela seria expirada
  no primeiro `GET /envio` seguinte, **antes de qualquer operador
  conseguir vê-la ou enviá-la**. A feature inteira estava morta, de
  ponta a ponta, sem nenhum teste pegando isso. Corrigido restringindo
  a expiração a `tipo = 'palpite'` — expirar por "kickoff já passou" só
  faz sentido pro palpite, nunca pro fechamento.
- **HIGH:** `gerar_fechamentos` calculava a variação de banca mostrada
  na mensagem como `(banca_depois da última aposta do grupo) - (banca_
  antes da primeira)`. Mas `bets.sequencia` é um contador **global** por
  usuário (Fase 6b, ordenado por kickoff+pick_id de **todas** as
  fixtures do usuário, não só desta) — se outra partida do mesmo
  usuário começasse no mesmo horário, a aposta dela podia cair
  intercalada entre as duas apostas desta fixture na sequência global,
  vazando o resultado de um jogo pra dentro da mensagem de fechamento
  de outro, silenciosamente. Corrigido somando o delta de cada aposta
  individualmente (`banca_depois - banca_antes` por linha), imune a
  qualquer intercalação.
- **MEDIUM, documentado (não corrigido por código):** o filtro "já tem
  fechamento?" é por `(usuário, fixture)` inteiro, não por pick — uma
  correção de slate que adicionar um pick novo a uma fixture já fechada
  nunca geraria fechamento pra esse pick específico (fica omitido pra
  sempre, nunca duplicado). Cenário raro, documentado no docstring do
  módulo, mesmo critério já aplicado a outros casos de borda raros no
  projeto.
- **MEDIUM, corrigido:** as regras "sem linguagem de projeção" e
  "resultado sempre com o período que cobre" (motivadas por regulação
  de publicidade de apostas no Brasil) não tinham teste de regressão
  próprio, só cobertura incidental. Adicionados: um teste que varre o
  corpo renderizado atrás de termos de projeção proibidos (guarda
  estrutural contra uma edição futura reintroduzir esse tipo de
  linguagem sem querer) e um teste explícito confirmando que a partida
  específica (times + placar) identifica o período coberto.

Rodado ao vivo contra o Postgres real (`scripts/gerar_fechamentos.py`,
`expirar_mensagens_vencidas`): sem erro, 0 gerado (esperado, sem
`bets` ainda). Mensagens de fechamento fluem pela `fila_envio`
existente sem nenhuma mudança nela — têm `fixture_id` real, então o
`INNER JOIN` já existente as inclui naturalmente.

### Resumo semanal (2026-08-18): fecha a Fase 6e, com a mudança de schema que tinha sido adiada

Pedido do usuário: "vamos continuar o desenvolvimento do ZapTips" — a
única pendência explícita da Fase 6e (item 1 da lista abaixo, antes
desta atualização) era justamente essa. A tensão de schema documentada
acima (`messages.fixture_id not null`, `fila_envio`/`contadores_do_dia`
com `INNER JOIN` em `fixtures`) foi resolvida de frente, não mais
adiada: `migrations/0027_messages_resumo_semanal.sql` derruba o
`not null` de `fixture_id` e amplia o `CHECK` de `tipo` pra aceitar
`'resumo_semanal'`.

Construído: `app/settlement/resumo_semanal.py` (cálculo puro — greens/
reds por contagem simples, não a taxa de acerto ponderada de
`app.settlement.metricas`; meio_green conta como green e meio_red como
red, decisão desta sessão pra simplificar a mensagem, sem confirmação do
PM) + `app/messaging.py` (`renderizar_resumo_semanal`, mesmas 4 regras
obrigatórias já usadas em `renderizar_fechamento` — banca sempre
"simulada", zero linguagem de projeção, período coberto explícito via
`inicio_semana`/`fim_semana`, rodapé legal obrigatório) +
`app/resumo_semanal_generator.py` (agrega `bets` da semana operacional
anterior por usuário, idempotente via chave própria com prefixo
`"resumo_semanal|"`) + `scripts/gerar_resumo_semanal.py` + job novo no
`scripts/agendador.py` (`resumo_semanal`, segundas 05h BRT — antes do
pipeline das 06h, mesma folga de propósito que o backup das 04h já
tinha). `app/pipeline.py` ganhou `segunda_da_semana_anterior(hoje)`,
correta mesmo rodando atrasada (ex.: terça, se o agendador ficou fora
do ar na segunda) porque sempre recalcula a partir da segunda da semana
corrente, nunca de um contador incremental.

`fila_envio`/`contadores_do_dia` (`app/console/queries.py`) passaram de
`INNER JOIN` pra `LEFT JOIN` em `fixtures` — sem isso, toda mensagem de
resumo semanal (fixture_id NULL por design) ficaria invisível na fila
inteira, mesma classe de bug já corrigida uma vez pra `resumo_do_dia`/
`universo_da_sessao` no checklist manual de sessão (Fase 6e, entrada
acima). `MensagemNaFila` ganhou `tipo` e os campos de fixture viraram
opcionais; `_mensagem_para_exibicao` (`app/console/rotas_envio.py`)
deriva um `rotulo` ("Resumo semanal" no lugar de "X x Y") e
`_card_mensagem.html` omite a linha de kickoff quando não há partida.

**Achado real do `code-reviewer` (HIGH), corrigido antes de fechar:**
`scripts/gerar_resumo_semanal.py main()` normalizava
`args.inicio_semana` via `segunda_da_semana_anterior` e depois
`executar()` normalizava de novo — como essa função transforma uma data
na segunda da semana ANTERIOR a ela (não na segunda da própria semana),
um operador rodando `--inicio-semana 2026-08-10` (intenção: regenerar a
semana de 10-16/08) geraria silenciosamente a semana de 03-09/08, sem
erro nem aviso. Não pego pelos 955 testes porque não havia teste nenhum
pra `main()`/`--inicio-semana` até então. Corrigido removendo a
normalização de `main()` — `--inicio-semana` agora espera a própria
segunda-feira da semana desejada, passada direto, mesmo padrão de
`--data` em `scripts/gerar_fechamentos.py`. `tests/
test_gerar_resumo_semanal.py` (3 casos) trava o comportamento certo:
`executar()` com data explícita não normaliza, `main()` com a flag não
normaliza duas vezes, e o caminho default (sem flag) normaliza uma vez
só a partir de hoje. `security-reviewer` em paralelo não achou nenhum
CRITICAL/HIGH/MEDIUM (injeção, autoescape, link do WhatsApp, colisão de
idempotency key entre os 3 tipos de mensagem e o gate de assinante ativo
pós-`LEFT JOIN` — todos conferidos e OK).

Rodado ao vivo contra o Postgres real: migration aplicada,
`scripts/gerar_resumo_semanal.py` gerou 1 mensagem real (`fixture_id`
NULL, corpo com banca simulada R$ 1000,00 → R$ 980,00, ROI -100%, a
única aposta real do projeto até agora) na primeira execução, 0 na
segunda (idempotente confirmado), e o `--inicio-semana` corrigido
reportou a semana certa depois do fix. `_card_mensagem.html` renderizado
isoladamente pra essa mensagem sem crash de `StrictUndefined`. 958
testes no projeto (subiu de 955 antes desta entrada).

### Pendências explícitas da Fase 6 (6a/6b/6c/6d/6e)

1. Parser completo de "cartões, condição por time" (Fase 6a) — falta
   texto real pra validar.
2. Uso auxiliar do `/settlements` do OddsPapi (Fase 6a) — não existe.
3. Alerta de 15% de não-liquidáveis por fonte (Fase 6a) — não existe
   canal de alerta no projeto ainda.
4. Contagem de revisão manual pendente não aparece no console `/saude`
   — só via CLI (`scripts/liquidacao.py listar`).
5. `scripts/relatorio.py` só tem CLI — nenhuma rota de console mostra
   métricas de usuário ou performance por fonte ainda.
6. Filtro "já tem fechamento?" por fixture inteira, não por pick (ver
   Fase 6e acima) — aceito, não corrigido, cenário raro.
7. **Atualização (Fase 7):** o critério de aceite de ponta a ponta da
   Fase 6 foi validado com dado real nesta sessão (ver seção Fase 7
   abaixo) — banca, ROI, taxa de acerto e mensagem de fechamento todos
   conferidos contra um pick real liquidado. Ainda com volume de 1,
   longe do suficiente pra validar limite diário/conflito de verdade.

## Fase 7 — Operação: escopo central concluído (página pública adiada)

Pedido do usuário: "Fase 7 (scheduler/operação)". Antes de codar,
achei uma tensão real: a spec pede uma "página pública de performance"
regenerada ao fim da liquidação diária — mas a decisão já fechada no
topo deste documento ("Ambiente de execução") diz explicitamente "roda
só na máquina local do PM, sem servidor". Uma página **pública**
pressupõe algo acessível pela internet, contradizendo isso.

**Decisão tomada com o usuário (pergunta feita antes de codar):**
construir as quatro partes sem conflito arquitetural nesta sessão
(agendador, health check, relatório diário, backup) e deixar a página
pública como pendência explícita, exigindo uma decisão de hospedagem
antes de qualquer código.

### O que foi construído

- **`scripts/agendador.py`** — processo único de longa duração
  (`APScheduler`, novo pacote nesta sessão) com 5 jobs: pipeline diário
  às 6h BRT, coleta de resultados e liquidação a cada 30min
  (independentes do slate), fechamento diário às 23h (`master_ledger`
  → `bets` → mensagens de fechamento, nessa ordem — resumo semanal
  **não** está aqui, adiado desde a Fase 6e), backup às 4h. Cada job
  isolado via `_rodar_job` — exceção de um nunca derruba o processo nem
  os outros jobs agendados.
- **`scripts/health.py`** — CLI que reaproveita literalmente as mesmas
  funções de `app.console.queries`/`rules` que alimentam a aba `/saude`
  (Fase 5c), nunca uma segunda implementação da mesma pergunta.
- **`app/relatorio_diario.py`** + subcomando `scripts/relatorio.py
  diario` — envios do dia, pulos e motivos, opt-outs, liquidações e
  taxa de não liquidados.
- **`scripts/backup.py`** — dump completo do Postgres via `pg_dump`,
  processo único, sem serviço gerenciado ("Escala definida").

**Achado real que bloqueava o agendador chamar dois scripts:**
`scripts/run_pipeline.py` e `scripts/collect_results.py` eram os
**únicos** dois scripts do projeto sem a separação `executar()`/`main()`
que todo o resto já seguia — o agendador precisa chamar a lógica
programaticamente, sem depender de `sys.argv`. Refatorados com cuidado
(comportamento preservado, mesmos testes existentes continuam
passando) e validados ao vivo contra o Postgres real depois da mudança.
Achei e corrigi um bug real meu mesmo nesse processo: `collect_results.
executar()` esqueceu de definir `settings` depois da extração, dando
`NameError` na primeira chamada de rede — pego rodando ao vivo, não
pelos testes (`FakeCursor` não exercita esse caminho).

### Primeira validação real de ponta a ponta da Fase 6 inteira

Rodando `collect_results` ao vivo pela primeira vez nesta sessão, 6
fixtures fecharam de verdade. Isso permitiu rodar a cadeia completa
`liquidar_picks` → `build_master_ledger` → `build_bets` →
`gerar_fechamentos` contra dado real pela primeira vez — não só
Postgres vazio como em todas as validações anteriores. Resultado:
1 pick liquidado (`vinculado`, "Avai vence" @ 1.82, resultado `red`),
banca simulada 1000→980, mensagem de fechamento renderizada
corretamente ("Avaí 0 x 1 CRB... ❌ Red... Banca simulada: R$ 980.00
(R$ -20.00)..."), relatório de usuário e de fonte batendo com os
mesmos números. Todo o trabalho de revisão desta sessão (Fase 6a–6e)
se confirmou correto contra produção real, não só contra `FakeCursor`.

### Revisão do `code-reviewer`: 1 HIGH real + 1 MEDIUM + 1 LOW, todos corrigidos

- **HIGH:** `app/relatorio_diario.py` comparava colunas `timestamptz`
  via `coluna::date = %s` contra a data de `data_operacional()`
  (calculada em `America/Sao_Paulo`) — mas `::date` avalia no fuso da
  **sessão** do Postgres (UTC, nada no projeto fixa o fuso da conexão),
  não no fuso operacional. Um envio às 21h30 BRT (00h30 UTC do dia
  seguinte) seria contado no relatório do dia **errado** —
  silenciosamente, exatamente na janela que sobrepõe o job de
  fechamento das 23h. **Mesma classe de bug já corrigida duas vezes
  nesta sessão** (Fase 6b, limites de assinatura em UTC cru; e a
  própria razão de `data_operacional()` existir, Fase 5a) — reaplicada
  aqui. Corrigido calculando os limites UTC do dia brasileiro
  explicitamente (`_limites_utc_do_dia`), comparando por intervalo
  (`>= ... and < ...`) em vez de `::date`. Nota: `app/console/queries.py`
  tem o mesmo padrão `::date` pré-existente (não introduzido nesta
  sessão) alimentando `/saude`/`scripts/health.py` — fica como
  pendência de follow-up, não corrigido agora.
- **MEDIUM:** `scripts/backup.py` passava a connection string completa
  (com a senha) como argumento de linha de comando pro `pg_dump` —
  visível no process list da máquina durante a execução. Corrigido
  extraindo a senha da URL e passando via variável de ambiente
  (`PGPASSWORD`), nunca em argv. Achado real por conta própria ao
  ajustar o teste: a função de sanitização (`_sanitizar`) fazia replace
  da URL inteira, frágil (só pegaria vazamento se aparecesse exatamente
  como a URL completa) — corrigida pra redigir a senha isolada.
- **LOW:** `_rodar_job` (agendador) tinha o log de início **fora** do
  `try` — uma falha hipotética no próprio log escaparia do isolamento
  de exceção. Corrigido, sem custo.

Suíte: 918 testes. Rodado ao vivo: `scripts.relatorio diario` contra
Postgres real (mostra a liquidação real do dia); `scripts.backup`
reporta corretamente `pg_dump_nao_encontrado_no_path` — dependência
externa que falta instalar nesta máquina, não um bug.

### Pendências explícitas da Fase 7

1. ~~Página pública de performance — não construída~~ — construída em
   sessão posterior (ver "Página pública de performance" abaixo).
2. `pg_dump` não está instalado na máquina do PM — `scripts/backup.py`
   funciona (falha graciosamente), mas precisa da ferramenta cliente do
   Postgres presente pra gerar um backup de verdade.
3. Mesmo padrão `coluna::date = %s` em `app/console/queries.py`
   (`/saude`, `scripts/health.py`) não foi corrigido nesta sessão — só
   o novo código (`relatorio_diario.py`). Revisitar.
4. ~~Resumo semanal (Fase 6e) continua fora~~ — construído em sessão
   posterior (2026-08-18, ver seção Fase 6e acima); ganhou job próprio
   (`resumo_semanal`, segundas 05h BRT), não o de fechamento diário.
5. Agendador nunca rodou de fato por um dia inteiro em produção — só
   testado localmente (import, registro dos 6 jobs, start/stop limpo).

## Página pública de performance (Fase 7, fechamento da pendência): concluída

Reconstruído por leitura de código nesta sessão (2026-08-20) — os
arquivos já existiam no projeto, criados numa sessão anterior sem
entrada correspondente neste documento; o texto abaixo descreve o que o
código faz e por quê, a partir da leitura direta (docstrings e
implementação), não de um relato original do PM.

`app/relatorio_publico.py` (DB-shape: lê `master_ledger` inteiro — Fase
6b — e simula com a banca/stake **default** do produto, nunca a config
de um assinante individual, "página usa o extrato mestre completo, não
expõe dado individual") + `app/settlement/metricas_publicas.py`
(reaproveita `app.settlement.metricas.calcular_metricas`, Fase 6c, sem
duplicar fórmula — só decide os 3 períodos: `"7 dias"`, `"30 dias"`,
`"Desde o início"`, e monta a curva de banca ponto a ponto) +
`app/pagina_publica.py` (dois artefatos puros: HTML de arquivo único
com CSS/SVG inline, sem JS/CDN/chamada de rede, e um resumo em texto
pronto pra colar no WhatsApp) + `scripts/gerar_pagina_publica.py`
(CLI/`executar()` que escreve `public/index.html` e `public/resumo.txt`,
sempre sobrescritos no mesmo caminho — URL estável pra hospedar sem
reconfigurar).

**Decisão que resolve a tensão "página pública" vs. "sem servidor"
(ver Fase 7 acima):** o script só **gera o arquivo estático localmente**
— publicar (upload pra Netlify Drop, GitHub Pages, etc.) continua sendo
um passo manual do operador, nunca automatizado pelo projeto. Isso não
contradiz mais a decisão de arquitetura, porque nenhum servidor novo
passa a rodar — é geração de artefato, igual a `scripts/backup.py`.

Regras de apresentação obrigatórias no código (não configuráveis, mesmo
padrão de `app/messaging.py`): "simulada" acompanha toda menção à banca;
frase fixa de metodologia (banca inicial, stake, **piso publicado**,
nunca a odd real obtida pelo assinante); nenhuma linguagem de
projeção/previsão; todo número vem com o período que cobre;
`rodape_legal` obrigatório (18+, jogo responsável); `curva_banca`/
`DadosPublicos` só carregam números agregados — nenhum `user_id`/
telefone/nome chega nesta camada.

Wired em `scripts/agendador.py::_fechamento_diario` — roda por último,
depois de `build_master_ledger`/`build_bets`/`gerar_fechamentos`
(23h BRT), "regerada ao fim da liquidação diária" (spec), mas depende só
de `master_ledger`, já fresco pelo primeiro passo do job.

`public/` adicionado ao `.gitignore` (artefato gerado, mesmo tratamento
de `backups/`) e o próprio diretório ainda não existe em disco nesta
máquina (nunca rodado). Suíte do projeto em **985 testes** (era 958 ao
fim da Fase 6e) — a diferença de 27 testes é inteiramente destes 4
arquivos novos (`test_relatorio_publico.py`,
`test_settlement_metricas_publicas.py`, `test_pagina_publica.py`,
`test_gerar_pagina_publica.py`).

## Correção do bug de fuso em `contadores_do_dia` (pendência #3 da Fase 7): concluída

Pendência explícita desde o achado original em `app/relatorio_diario.py`
(Fase 7) e no checklist manual de sessão (Fase 6e): o mesmo padrão
`coluna::date = %s` já corrigido em `universo_da_sessao`/`resumo_do_dia`
(`app/console/queries.py`) e em `relatorio_diario.py` continuava vivo em
`contadores_do_dia` (mesmo arquivo, usada por `GET /envio` — a aba de
Envio do console, Fase 5d/6e), no filtro `enviadas_hoje`:
`m.enviada_em::date = %s::date`. Mesmo risco de sempre: `::date` avalia
no fuso da SESSÃO do Postgres (UTC por padrão), não em
`America/Sao_Paulo` — um envio às 21h30 BRT (00h30 UTC do dia seguinte)
seria contado no dia errado, bem na janela que mais importa pro operador
fechar a sessão de envio.

Corrigido com o mesmo padrão já estabelecido: `contadores_do_dia` agora
calcula `data_operacional(agora)` + `limites_utc_do_dia(...)` (ambos de
`app.pipeline`, já usados pelas outras duas funções do mesmo arquivo) e
troca o filtro pra `m.enviada_em >= %s and m.enviada_em < %s`. O filtro
`expirando_2h` (compara `kickoff_utc` contra `agora + 2h`, uma janela
móvel, não um dia de calendário) foi deixado intocado, corretamente —
não é a mesma classe de bug.

Auditoria de todo o projeto (`grep -rn "::date"`) confirmou que não
sobrava mais nenhuma outra ocorrência problemática do padrão: os únicos
outros `::date` restantes são em `app/messages_generator.py`
(comparação de datas puras, já calculadas em `America/Sao_Paulo` antes
de virar parâmetro — achado corrigido na Fase 6b) e `app/subs.py`
(`generate_series` de datas de calendário, nunca timestamptz) — nenhum
dos dois é a mesma classe de bug.

2 testes de regressão novos em `tests/test_console_queries_envio.py`
(`FakeCursor`, mesma convenção do arquivo): confirma ausência de
`::date` na SQL e o texto exato do filtro por intervalo, e confirma os
parâmetros `inicio_utc`/`fim_utc` calculados pra um horário real de
virada BRT/UTC (20h30 BRT = 23h30 UTC do mesmo dia). Revisado pelo
`code-reviewer`: **aprovado, 0 achados** — fix semanticamente correto,
consistente com o padrão já estabelecido, `expirando_2h` corretamente
preservado, testes corretos e idiomáticos. Suíte em **987 testes** (985
+ 2 novos).

## Nível 3 da hierarquia de odds — bloco nativo da ESPN: concluído

Pendência explícita desde a Fase 1g/4 ("adapter ainda não existe").
Antes de implementar, investiguei ao vivo o payload real da ESPN (não
confiei na descrição em prosa da Fase 1a, que só documentava a
*presença* do bloco de odds, nunca seu formato) — sonda rápida contra
`/scoreboard` e `/summary` de 7 ligas (bra.1, bra.2, eng.1, esp.1,
uefa.champions, ita.1, ger.1) em 2026-08-20. Dois achados reais que
mudam a implementação em relação ao que a documentação original
implicitamente supunha:

1. **Formato é odds americanas (moneyline)**, não decimais — ex.
   `"homeTeamOdds": {"moneyLine": -240}`. Precisa de conversão
   (`1 + moneyline/100` se positivo, `1 + 100/|moneyline|` se negativo)
   antes de qualquer comparação com o piso do produto.
2. **Nas 7 ligas testadas ao vivo, o único provider observado foi a
   DraftKings** — casa americana, não licenciada no Brasil, portanto
   nunca elegível pro nível 3. A sonda original da Fase 1a (2026-08-10,
   temporada anterior) tinha visto Bet365 em parte da amostra, mas isso
   não se reproduziu na amostra de hoje.

Antes de implementar de qualquer jeito, esse achado foi levado ao PM
(pergunta explícita: "vale construir sabendo que provavelmente não vai
resolver nada na prática hoje?"). Decisão: **sim, construir mesmo
assim** — custo baixo, cobre o caso raro em que uma casa licenciada
aparecer, e o fallback é seguro por design (nunca acha casa licenciada
= `None`, nunca chuta).

### O que foi construído

`app/espn_odds.py` (novo): `normalizar_nome_casa` (remove espaço/case —
o payload real usa `"Bet 365"` com espaço, `casas.nome` está cadastrado
como `"Bet365"` sem espaço, e `casas.aliases` está vazio — pendência
conhecida — então normalizar é o único jeito de bater os dois sem
depender de alias populado), `_moneyline_para_decimal` (`Decimal` com
`ROUND_HALF_UP`, 3 casas — mesma precisão de `picks.odd_referencia
numeric(6,3)`, mesma cautela contra ruído binário já usada em
`calcular_odd_minima`), `extrair_odds_licenciadas` (filtra só casas
licenciadas, tolera entrada malformada sem quebrar as demais, nunca usa
`hasOdds` do payload — não confiável, achado original da Fase 1a,
reconfirmado na sonda de hoje: veio `False` com o array `odds` de fato
preenchido).

`app/odds_resolution.py`: `resolver_odd_espn(pick, payload_summary,
casas_licenciadas_normalizadas)` — só tenta pra mercado `1x2`, reusa
`normalizar_selecao_1x2` (mesma restrição do nível 2, nunca chuta
dupla-chance/seleção ambígua), usa o **mínimo** entre as casas
licenciadas encontradas (mesmo raciocínio conservador do nível 2 — "o
produto promete um piso, não uma cotação"). `OrigemOdd` ganhou o
literal `"espn"` (`slate_picks.odd_referencia_origem` já tinha esse
valor no `CHECK` desde a migration 0018/Fase 5c, antecipando esta
implementação; `picks.odd_referencia_origem` nunca teve `CHECK`, então
não precisou de migration nova).

`scripts/resolve_odds.py`: reestruturado em 3 fases — leitura sem rede
(níveis 1/2, como já era) → rede só pras fixtures cujos picks realmente
precisam do nível 3 (`picks_candidatos_a_espn`, que replica a mesma
checagem de `resolver_odd_espn` pra não gastar uma chamada de rede num
pick que nunca poderia usar o resultado) → escrita sem rede. Mesmo
padrão de 3 fases já usado em `collect_results.py` (1 req/s,
`RATE_LIMIT_SECONDS`, falha numa fixture não derruba as demais).
`aplicar_resolucao` ganhou parâmetro opcional `odd_espn` (default
`None`, preserva 100% de compatibilidade com chamadas/testes antigos);
a prioridade é sempre `resolver_odd_referencia(...) or odd_espn` —
níveis 1/2 vencem sobre nível 3 quando ambos resolvem.

### Revisão do `code-reviewer`: 1 MEDIUM real, corrigido

`extrair_odds_licenciadas` quebrava com `AttributeError` se um item da
lista `odds` viesse `None` explícito (não só um campo interno nulo) —
mesma classe de bug já corrigida duas vezes no projeto
(`espn_fixtures.py`/`espn_summary.py`, Fase 1e/1f: `"venue": null`,
`"statistics": null` derrubando o parsing inteiro de um evento). Os
testes de entrada malformada existentes cobriam `provider: None`,
`homeTeamOdds: None` e `moneyLine` não numérico, mas nunca um item nulo
na própria lista. Corrigido com `isinstance(entrada, dict)` no topo do
loop, guarda que já é padrão no resto do projeto pra esse tipo de
payload sem contrato de estabilidade. Teste de regressão adicionado.

Todo o resto do review veio limpo: conversão moneyline↔decimal
verificada contra valores conhecidos (-110 → 1.909, +100 → 2.0),
prioridade nível 1/2 sobre nível 3 confirmada e testada, exclusão de
odd de origem manual (achado da Fase 4, "Rodada de extração assistida")
confirmada intacta, fase de rede corretamente escopada só aos
candidatos do nível 3, nenhuma regressão nos níveis 1/2 existentes.

Suíte em **1008 testes** (987 + 21 novos entre `test_espn_odds.py`,
extensões de `test_odds_resolution.py` e `test_resolve_odds.py`).
Nenhuma validação contra o Postgres real nesta entrada — a mudança
depende de picks reais com mercado `1x2` ainda não resolvidos por
nível 1/2 e de uma fixture cujo bloco de odds da ESPN traga casa
licenciada, cenário raro no volume atual (ver achado #2 acima); vale
revisitar quando/​se isso ocorrer de verdade em produção.

## Primeira mensagem real enviada via WhatsApp (2026-08-20): marco de produto

Pedido do PM: "rode o agendador e faça o sistema de controle geral
subir" seguido de "vamos continuar melhorando o sistema até conseguir
enviar a primeira mensagem via WhatsApp". Console (`scripts.console`) e
agendador (`scripts.agendador`) subidos em background, os dois
confirmados vivos (console respondendo 200 em `/saude`; agendador com
os 6 jobs registrados, fuso `America/Sao_Paulo`).

### Estado real encontrado, não fabricado

`scripts.health` mostrou pipeline do dia ainda não rodado (agendador só
dispara `pipeline_diario` às 6h, já passada) — rodado manualmente.
Resultado real: `extracao` degradada (sem crédito de API, esperado),
`slate` com 0 candidatos — os únicos 10 picks com odd resolvida no
banco eram de fixtures já passadas (08/08 a 16/08), sobra de sessões
anteriores; nenhum pick novo tinha odd ainda.

Processo de extração assistida (ver Fase 3/decisão permanente) rodado
sobre os 40 `raw_picks` pendentes: 52 picks inseridos, `link_picks`
vinculou 16 a fixtures reais, `resolve_odds` (agora com nível 1-3, ver
entrada acima) resolveu 9 — mas todos os 9 eram, de novo, fixtures já
passadas (o gate de status `vinculado`/`sem_odd` do script não filtra
por tempo). Dos 4 picks realmente novos ligados a fixtures futuras
(próximas 48h), nenhum tinha odd citada pela fonte nem cobertura no
OddsPapi/ESPN pro mercado deles (`ambas_marcam`/`over_under`, fora do
escopo dos níveis 2/3) — `sem_odd`, corretamente, não um bug.

**Investigação ao vivo antes de qualquer atalho:** consultada a API da
OddsPapi diretamente (não só via `collect_odds.py`) para as duas
partidas de Série B de hoje à noite (Athletic x CRB, Novorizontino x
América-MG) - `hasOdds: true` no payload bruto, mas `resolve_odds.py`
não achou odd 1x2 pra nenhuma das duas. **Correção de um diagnóstico
errado feito nesta mesma sessão:** a primeira leitura (rápida, sem
inspecionar o payload completo) concluiu que a chave de mercado `"101"`
não estava presente e que a bet365 usava IDs dinâmicos — **isso estava
errado**. Investigação mais cuidadosa (pedida pelo PM: "não sei o que
falta", levou a revisitar esse item) mostrou que a chave `"101"` **está
presente**, com preços reais (`2.35`/`3.20`/`3.00` pra Athletic x CRB,
`1.53`/`3.80`/`6.25` pra Novorizontino x América-MG), só que com
`"marketActive": false` — confirmado também na Betano pras mesmas duas
partidas (Superbet não checado, rate-limit 429 no meio da investigação,
`COOLDOWN_SECONDS` do provedor). O parser (`app.oddspapi._parse_fixture`,
`if not mercado.get("marketActive", True): return None`) está correto:
recusar um preço de mercado suspenso é a decisão certa - "piso
publicado" só faz sentido se for algo que o assinante consiga de fato
apostar agora. **Não é bug, não precisa de correção.** Hipótese não
testada: o mercado pode ativar mais perto do kickoff (a suspensão
observada foi ~7-8h antes do apito); vale revisitar rodando
`collect_odds.py` de novo poucas horas antes de uma partida de Série B
pra confirmar se isso é um padrão (mercados de ligas menores abrem
tarde) ou coincidência do dia.

### Decisão: usar o palpite manual do console com odd real verificada

Dado que nenhum caminho automático (níveis 1/2/3) tinha dado real
disponível pra uma fixture das próximas 24h, usei `claude-in-chrome`
pra consultar odds públicas reais (OddsPortal, aba "Classic Bookies")
pra Athletic Club x CRB (Série B, kickoff hoje 22h30 UTC) — várias casas
regulamentadas convergindo em ~2.40 pra vitória do Athletic Club.
Cadastrado via `/curadoria` → "Adicionar palpite manual" (mercado 1x2,
seleção "Athletic vence", odd 2.40) — real, verificada ao vivo contra
mercado, não inventada. Slate aprovado pelo console; `gerar_mensagens`
rodou dentro da mesma transação (Fase 5d) e gerou a mensagem real pro
único assinante ativo (o próprio operador).

### Falso alarme investigado e descartado

Ao abrir o link "Abrir no WhatsApp", a URL exibida pela ferramenta de
automação de navegador mostrava o emoji 🔞 do rodapé legal como um
caractere de erro (`%EF%BF%BD`, replacement character). Investigado
antes de "corrigir" qualquer coisa: `curl` direto no HTML servido por
`/envio` mostrou a codificação **correta** (`%F0%9F%94%9E`, UTF-8
válido) tanto no link individual quanto no combinado
("abrir tudo") — confirmado também que `corpo_renderizado` já estava
correto no Postgres e que `urllib.parse.quote` codifica o emoji
corretamente de forma isolada. A garantia real: **nenhum bug**, o
caractere estranho era só como a ferramenta de automação exibiu a URL
pra mim, não o que de fato foi pro WhatsApp - confirmado por leitura
direta do dado em cada camada antes de mexer em qualquer código.

### Resultado

Mensagem enviada de verdade pelo PM via WhatsApp Web, confirmado por
ele e validado no Postgres: `messages.status = 'enviada'`,
`enviada_em` real (2026-08-20 15:21 UTC), tanto a mensagem de palpite
quanto o resumo semanal que já estava na fila. **Primeiro envio real de
ponta a ponta do produto** - pipeline → extração → vínculo → odd
(manual, dado real verificado) → curadoria → aprovação → geração de
mensagem → fila de envio → WhatsApp de verdade. Console e agendador
seguem rodando em background nesta máquina.

## Checklist manual do modo sessão (pendência da Fase 5d): concluído, com achado real corrigido

Pendência explícita desde a Fase 5d ("o checklist interativo de
navegador do `sessao.js` não foi exercido num browser real nesta
sessão"). Console subido localmente (`uv run python -m scripts.console`)
e testado via `claude-in-chrome` contra o Postgres real, não fakes.

Gate de acesso à aba Envio (`avaliar_acesso_envio`) exige pipeline rodado
hoje **e** slate de hoje aprovado — satisfeito rodando
`scripts/run_pipeline.py` (fechou `degradado`, só pela extração sem
crédito de API, esperado) e aprovando o slate vazio de hoje na
Curadoria. Isso liberou a fila real, que já tinha 1 mensagem `pronta`
(fechamento de Avaí x CRB, sobrando da validação da Fase 7).

**Os 4 itens do checklist, todos confirmados ao vivo:**
- Contagem regressiva rodando e liberando o botão "Marcar como enviada"
  no fim do intervalo (30s → 18s → 9s, depois liberado).
- Reentrância real após F5: recarregar a página no meio da contagem
  manteve o tempo restante (9s), não reiniciou em 30s — confirma que o
  timer usa o epoch persistido em `sessionStorage`, não estado em
  memória perdido no reload.
- `Enter` fora do campo `motivo` aciona o atalho "Marcar como enviada".
- `Enter` **dentro** do campo `motivo` não rouba o atalho — dispara a
  validação nativa do formulário "Pular" (`Please fill out this field`,
  motivo vazio), confirmando que os dois formulários no mesmo card não
  competem pelo `Enter` um do outro.

### Achado real: mensagem de fechamento nunca aparecia no resumo de fim de sessão

Depois de marcar a mensagem como enviada via atalho `Enter`, a fila
zerou e a sessão se auto-encerrou (D13) — mas a tela de "Sessão
concluída" mostrou **"Enviadas: 0"**, apesar de `messages.status` estar
corretamente `'enviada'` no banco (confirmado por query direta). Causa:
`app.console.queries.resumo_do_dia` e `universo_da_sessao` fazem `join`
(ou `in (select ... where data = %s)`) contra `daily_slates` pra
escopar "hoje" — mas mensagem de `tipo='fechamento'` (Fase 6e) tem
`slate_id` **sempre `NULL`**, por design (fechamento não pertence a
slate nenhum). Um `INNER JOIN`/`IN` puro exclui essa linha
estruturalmente, **qualquer que seja a data pedida** — não um problema
de fuso horário, a linha nunca entra no resultado.

Consequência dupla, mesma causa raiz:
- `resumo_do_dia`: toda mensagem de fechamento fica invisível no resumo
  de fim de sessão (enviadas/expiradas/prontas restantes e a lista de
  puladas) — o operador vê números menores do que o trabalho real feito.
- `universo_da_sessao`: um assinante cuja **única** mensagem do dia
  fosse um fechamento cairia do universo estável assim que ela deixasse
  de estar `'pronta'` (resolvida) — reintroduzindo, só pra fechamento,
  o mesmo reembaralhamento de `ordem_da_sessao` que o desenho de
  universo estável (D19, Fase 5d) existe pra evitar. Não observado ao
  vivo nesta sessão (só havia 1 assinante/1 mensagem), mas é uma
  consequência lógica direta do mesmo `join`.

**Corrigido:** as duas funções ganharam um terceiro critério de
pertencimento ao dia — `m.slate_id is null and m.gerada_em` dentro dos
limites UTC do dia operacional (`America/Sao_Paulo`), em vez de
depender só de `daily_slates`. `resumo_do_dia` trocou o `join` por
`left join` mais esse critério no `where`. O helper de limites UTC
(`_limites_utc_do_dia`, que já existia privado em
`app/relatorio_diario.py` desde a Fase 7, pra evitar o mesmo problema de
`coluna::date` avaliar no fuso da sessão do Postgres) foi promovido a
público — `limites_utc_do_dia`, em `app/pipeline.py`, ao lado de
`data_operacional()` — e agora é reaproveitado nos dois lugares, em vez
de duplicado (mesmo critério da revisão holística pós-Fase 2). 920
testes no projeto (subiu de 918): 2 regressões novas (uma por função) +
os 2 testes de `limites_utc_do_dia` migrados pra `tests/test_pipeline.py`
(a função não é mais exclusiva de `relatorio_diario.py`).

**Validado ao vivo, não só com `FakeCursor`:** `resumo_do_dia` chamada
direto contra o Postgres real pro dia em que a mensagem foi gerada
(12/08) voltou `(1, 0, 0, [])` — antes da correção, teria voltado
`(0, 0, 0, [])` pra qualquer data, sem exceção.

**Nota de design, não um bug novo:** o escopo de "dia" pro fechamento
ficou atrelado a `gerada_em` (quando a mensagem foi gerada), não a
`enviada_em` (quando foi de fato enviada) — mesma convenção já usada
pra mensagem de palpite (`daily_slates.data`, que também é o dia da
geração, não do envio). Uma mensagem sobrando de um dia anterior e
enviada só numa sessão posterior conta no resumo do dia em que foi
**gerada**, não no dia em que o operador finalmente a enviou — esse já
era o comportamento aceito pra mensagem de palpite antes desta sessão;
a correção só tornou o fechamento consistente com o mesmo critério, não
introduziu uma regra nova.

Pendência já registrada acima (item 3 da Fase 7, `coluna::date = %s` em
`/saude`/`scripts/health.py`) continua sem correção — fora do escopo
desta rodada, que tratou só as duas funções que o checklist expôs.

## Rodada de extração assistida + matching real (2026-08-13): dois achados reais corrigidos

Primeira execução do processo de extração assistida por agente definido
nesta sessão (ver "Decisão permanente" acima), sobre os 21 `raw_picks`
pendentes deixados pelo `run_pipeline.py` de hoje. Pedido do PM: "rode".

### Achado 1: palpite manual do console nunca marcado como extraído

`app.console.acoes.criar_palpite_manual` (Fase 5d) inseria a linha em
`raw_picks` sem preencher `extraido_em` — o raw_pick nasce já com um
`pick` estruturado (o insert seguinte na mesma função), mas ficava pra
sempre elegível pra `buscar_raw_picks_pendentes`. Descoberto porque
apareceu entre os 21 pendentes de hoje: reprocessá-lo pela extração
assistida criaria um `pick` duplicado apontando pro mesmo
`raw_pick_id`. Corrigido preenchendo `extraido_em = now()` na própria
inserção; a entrada já existente em produção foi fechada retroativamente
com `marcar_extraidos` (mesma função de produção, sem criar pick novo —
confirmado antes que só havia 1 `pick` pra aquele `raw_pick_id`). Teste
de regressão em `tests/test_console_acoes_manual.py`.

### Achado 2: resolve_odds.py sobrescrevia odd definida manualmente

Rodando `scripts/resolve_odds.py` de novo (agora com picks novos
vinculados), o script processou TODO pick com `status='vinculado'` —
inclusive o palpite manual do Avaí x CRB, já aprovado/enviado/liquidado
dias antes. A hierarquia documentada trata odd manual como nível 4,
"fora de escopo" dos níveis 1/2 automáticos deste script — mas nada
impedia isso na prática: a odd digitada pelo operador (1.90, origem
`manual`) foi silenciosamente sobrescrita por um valor do OddsPapi
(2.75, origem `oddspapi`). O dado já enviado/liquidado usa a cópia
congelada em `slate_picks` (não afetada — confirmado por query direta),
mas o registro vivo em `picks` foi corrompido. Corrigido excluindo
`odd_referencia_origem = 'manual'` da query de `buscar_picks_vinculados`;
o valor corrompido foi restaurado manualmente a partir do registro
congelado em `slate_picks` (1.90 / manual / piso 1.82). Teste de
regressão em `tests/test_resolve_odds.py`.

### Resultado da rodada

- **29 picks extraídos** de 20 `raw_picks` reais (Eagle Predict
  multi-palpite + SDA "Palpite X x Y"), 100% de resolução de `casa_id`,
  nenhum caso ambíguo (confiança 0.90–0.97).
- **12 picks vinculados** a fixtures reais pela primeira vez desde a
  Fase 4 (jogos de Libertadores/Sul-Americana da semana) — antes só
  havia 1 (Goiás x Londrina, segue `sem_odd`).
- **0 resolveram odd**: os 12 novos são `ambas_marcam`/`over_under`/
  `handicap` sem odd citada na fonte, fora da cobertura do OddsPapi
  nível 2 (só `1x2`) — corretamente `sem_odd`, não é bug.
- Uma correção de slate vazia (`daily_slates`, aparecida durante o
  checklist de sessão mais cedo nesta mesma sessão — nenhuma ação
  registrada explica a origem exata) ficou parada bloqueando
  `build_slate.py`; aprovada pelo console, com confirmação explícita do
  PM, pra destravar.
- `build_slate.py` rodou limpo: 0 candidatos, consistente com nenhum
  pick ter odd resolvida ainda.
- **1076 picks no total** (1061 `extraido`, 1 `revisao_manual`, 13
  `sem_odd`, 1 `vinculado`), **0 `raw_picks` pendentes de extração**.
  922 testes no projeto (subiu de 920 no início da sessão).

Revisado pelo `code-reviewer` ao fim da sessão, sobre os 5 arquivos
tocados hoje (`app/pipeline.py`, `app/relatorio_diario.py`,
`app/console/queries.py`, `app/console/acoes.py`,
`scripts/resolve_odds.py`) e uma varredura cruzada por outros pontos do
mesmo padrão de bug (`link_picks.py`, `build_slate.py`, outros inserts
em `raw_picks`): **aprovado, 0 achados**. Confirmou que nenhum outro
local do projeto reprocessa `picks`/`slate_picks`/`messages` sem
escopo por status/proveniência, e que nenhum outro ponto de insert em
`raw_picks` está sem `extraido_em`.

## Próximos passos

1. ~~Rodar o checklist manual de navegador do modo sessão~~ — concluído
   nesta sessão (ver seção acima), com achado real corrigido.
2. ~~Quando houver créditos de API: rodar `scripts/extract_picks.py`~~ —
   não vai acontecer, decisão permanente do PM (2026-08-13, sem
   orçamento pra créditos de API). Substituído por: quando o PM pedir
   ("extrai os picks pendentes"), repetir o processo de extração
   assistida por agente sobre os `raw_picks` pendentes, mesmo caminho
   validado no backlog de 767 (ver Fase 3 acima). Os critérios de
   aceite que dependiam da API real (custo por 100 posts, acurácia
   específica do Haiku 4.5) não se aplicam mais.
3. `scripts/run_pipeline.py` (Fase 5a) já liga `link_picks`/
   `resolve_odds`/`build_slate` automaticamente — falta rodá-lo
   recorrentemente por alguns dias (Fase 7, scheduler) pra acumular
   fixtures/picks o suficiente e validar os critérios de aceite do
   documento original com volume real (conflito resolvido de verdade,
   limite diário atingido). Atualizado 2026-08-13: 13 picks agora
   vinculados (12 novos + Goiás x Londrina), mas nenhum com odd
   resolvida ainda (mercados fora da cobertura do OddsPapi nível 2) —
   ver "Rodada de extração assistida" acima. Ainda não validado com
   volume suficiente pra conflito real/limite diário.
4. Nível 3 da hierarquia de odds (bloco nativo da ESPN) — adapter ainda
   não existe. Nível 1 (fonte cita casa licenciada) e nível 2 (OddsPapi,
   só `1x2`) já funcionam.
5. Normalização de seleção pra detecção de conflito (`app/slate.py`) só
   cobre o mercado `1x2` hoje (reaproveita
   `app.odds_resolution.normalizar_selecao_1x2`) — mercados como
   `over_under`/`ambas_marcam`/`handicap` ainda comparam texto bruto, o
   que pode diluir consenso real entre fontes com fraseado diferente
   (mesmo problema já corrigido pro `1x2` nesta sessão). Também falta
   comparar `linha` (a extração da Fase 3 não populou essa coluna).
   Limitação conhecida, não resolvida especulativamente — só vale a
   pena depois de ver volume real desses mercados.
6. Voltar em ~1 semana pra rodar `scripts/collect_results.py` contra
   fixtures que já passaram de kickoff+2h de verdade, e responder a
   pergunta 7 da Fase 1a (latência até o placar virar definitivo), que
   segue sem dado real.
7. Considerar estender `app/matcher.py` para reconhecer sufixo de estado
   separado por espaço (não só `-XX`/`/XX`), o que ajudaria a resolver
   parte da ambiguidade residual da família Atlético/Botafogo — mas só
   vale a pena depois de ver quantos casos reais isso afeta em produção,
   não como exercício especulativo agora.
8. Fase 2, Fonte 3 em diante (documento tem mais fontes além de Eagle
   Predict e SDA) — avaliar se vale mais fonte ou se o volume atual
   (1076 picks, 2026-08-13) já é suficiente para validar o pipeline de
   ponta a ponta.
9. Popular `casas.aliases` com variações reais de grafia — menos urgente
   agora que o backfill mostrou 100% de resolução de `casa_id` sem
   alias nenhum, mas ainda vale quando aparecer grafia divergente de
   verdade (ex.: "Bet 365" com espaço).
10. Com a Fase 5 completa (5a–5d), o console cobre o ciclo inteiro de
    curadoria → aprovação → geração de mensagem → envio assistido. A
    decisão Fase 6 vs. Fase 7 já foi resolvida a favor da Fase 6 — Fase 7
    (scheduler via APScheduler) continua pendente, sem data.
11. **Fase 6 (6a/6b/6c/6d/6e) está fechada por completo** — motor de
    liquidação, simulação de banca (`master_ledger`/`bets`), métricas
    por usuário, performance por fonte, mensagem de fechamento do
    palpite e resumo semanal, todos com CLI e testados contra o
    Postgres real (ver seções próprias acima, resumo semanal fechado em
    2026-08-18). Restam só as pendências pontuais listadas na seção
    "Pendências explícitas da Fase 6" acima (parser de cartões por
    time, alerta de 15%, etc.), nenhuma delas bloqueando a fase.
