# Prompt para Claude Code: Sistema de Palpites Esportivos com Envio Assistido

> Especificação completa. As quatro fontes já foram investigadas e estão especificadas. Copie tudo abaixo da linha para o Claude Code.

---

## Contexto

Você vai construir um sistema que coleta palpites de futebol de fontes públicas, cruza cada palpite com os dados oficiais da partida, calcula uma odd de referência e um piso mínimo, e monta as mensagens diárias de um serviço de assinatura por WhatsApp.

O envio é manual: o sistema prepara tudo e eu disparo cada mensagem, como se estivesse mandando para um amigo.

O produto não é o palpite. É a curadoria entre várias fontes mais o histórico auditável de resultados. Por isso o motor de liquidação e o extrato de banca não são acessório, são o núcleo.

Sou Product Manager, não engenheiro de software. Escreva código legível, comente decisões não óbvias e me explique trade-offs quando existirem duas escolhas razoáveis. Prefiro entender o sistema a ter o sistema pronto rápido.

**Antes de escrever qualquer código:** leia esta especificação inteira, me faça as perguntas que ficaram em aberto e proponha o plano de fases. Só comece a implementar depois que eu aprovar.

## Decisões já tomadas

Avaliadas e fechadas. Não reabra sem argumento forte, e se tiver o argumento, traga antes de implementar.

**Negócio**

1. **Assinatura mensal paga, sem link de afiliado.** A casa de aposta aparece só como referência de onde a cotação foi vista.
2. **Sem período de teste, sem renovação automática, sem fluxo de cancelamento.** Pagamento por Pix registrado na mão. A assinatura vence e o acesso para. Quem quer continuar, paga de novo.
3. **Teto de 50 assinantes ativos nesta fase.** É trava no código, não sugestão.
4. **Slate único diário, igual para todos**, com curadoria manual obrigatória antes de qualquer envio.

**Dados**

5. **ESPN como única fonte de partidas, placar e estatística.** Sem API-Football, sem segundo provedor. Motivo na Fase 1.
6. **OddsPapi apenas como complemento** para odd de referência, quando a fonte não traz casa licenciada no Brasil.
7. **Toda fonte nova entra em quarentena:** coletada e liquidada, mas nunca publicada, até 60 dias de medição autorizarem.

**Produto**

8. **A mensagem não promete odd, promete piso.** "Odd aproximada X, não aposte abaixo de Y."
9. **O extrato é liquidado pela odd mínima publicada**, assumindo sempre que a aposta foi feita. É simplificação declarada, e a metodologia aparece em toda exibição.
10. **Envio manual, sem automação de WhatsApp.** Nada de Cloud API da Meta, nada de Baileys, whatsapp-web.js ou Evolution API. Motivo na Fase 5.

## Regras de trabalho

1. Crie um `CLAUDE.md` na raiz com arquitetura, comandos, variáveis de ambiente e decisões tomadas. Mantenha atualizado a cada fase.
2. Trabalhe em fases. Ao final de cada uma, pare, rode os testes, me mostre o que funciona e espere aprovação.
3. Nenhuma chave em código. Tudo em `.env`, com `.env.example` versionado.
4. Todo módulo externo (fonte de palpite, provedor de dados) entra por uma interface/adapter.
5. Testes com dados reais salvos em fixtures. Nada de mock que sempre passa.
6. Commits pequenos e descritivos.

## Stack

- Python 3.11+
- Postgres via Supabase (já uso Supabase em outro projeto)
- `httpx` para HTTP, `tenacity` para retry, `pydantic` para schemas
- OddsPapi (`api.oddspapi.io/v4`) para odds de referência de casas licenciadas no Brasil
- `rapidfuzz` para matching de nomes
- `beautifulsoup4` + `httpx` para coleta. `playwright` só onde a página exigir JS
- `telethon` apenas se aparecer canal de Telegram sem versão pública em `t.me/s/`. Nenhuma fonte atual precisa
- API da Anthropic (`claude-sonnet-4-6`) para extração de palpites em texto livre
- `FastAPI` + `Jinja2` para o console local
- `APScheduler` para a execução diária
- `pytest`, `structlog`

Se discordar de alguma escolha, diga o motivo antes de trocar.

---

# Arquitetura

```
   SDA      Eagle Predict      Andy Robson       APWin
(publica)     (publica)       (quarentena)   (quarentena)
    |             |                 |              |
    +-------------+--------+--------+--------------+
                           |
                  [Coleta e extração]  ->  raw_picks, picks
                           |
                  [Matcher + ESPN]  ->  fixtures, transmissão
                           |
                  [Odd de referência + piso]  ->  para TODO palpite
                           |
              +------------+------------+
              |                         |
     [Curadoria manual]          (quarentena pula)
              |                         |
       [Console: envio]                 |
              |                         |
              +------------+------------+
                           |
                  [Liquidação: ESPN]
                           |
              +------------+------------+
              |                         |
   [Banca do assinante]        [Relatório de fontes]
   só o que foi enviado        tudo, publicado ou não
```

Duas trilhas, um motor. A odd é capturada antes da bifurcação, e é isso que permite calcular ROI real também para o que nunca foi publicado.

Cada camada roda isolada. Se um coletor quebrar, o resto continua operando com o que já está no banco.

---

# Fase 0: Fundação

Estruture o projeto, configure Supabase, crie as migrations e o `.env.example`.

## Schema

```sql
-- Times e reconciliação de nomes
teams (id, nome_canonico, pais, espn_team_id, criado_em)
team_aliases (id, team_id, alias, alias_normalizado, fonte, confianca)

-- Partidas
fixtures (
  id, espn_event_id UNIQUE, oddspapi_fixture_id,
  liga, temporada, rodada,
  home_team_id, away_team_id,
  kickoff_utc, status, estadio,
  placar_casa, placar_fora,
  placar_ht_casa, placar_ht_fora,
  encerrado_em, atualizado_em
)
  -- status: agendada | ao_vivo | encerrada | adiada | cancelada

fixture_stats (id, fixture_id, time_id, escanteios, cartoes_amarelos,
               cartoes_vermelhos, finalizacoes, posse, origem, coletado_em)

broadcasts (id, fixture_id, canal, pais, tipo, origem)
  -- tipo: tv_aberta | tv_fechada | streaming
  -- origem: espn | manual

broadcast_rules (id, liga, dia_semana, canais[], observacao)
  -- tabela que eu preencho na mão, fallback para o Brasil

-- Casas de aposta (só referência, não há afiliação)
casas (id, nome, slug_oddspapi, aliases[], licenciada_br, ativa)

-- Odds de referência, capturadas na publicação do slate
odds_referencia (
  id, fixture_id, casa_id,
  mercado, selecao, linha,
  valor, origem,          -- oddspapi | manual
  capturada_em
)

-- Mapeamento de ligas entre provedores
league_map (id, espn_league_code, oddspapi_tournament_id, nome, ativa)

-- Controle de execução do pipeline
pipeline_runs (
  id, data_referencia UNIQUE,
  status,            -- rodando | pronto | degradado | falhou
  etapa_atual,
  iniciado_em, finalizado_em
)

pipeline_stages (
  id, run_id, etapa, ordem,
  status,            -- pendente | rodando | ok | degradado | falhou
  itens_ok, itens_erro,
  iniciado_em, finalizado_em, detalhe_json
)

-- Palpites aguardando partida que ainda não existe no banco
picks_orfaos (id, pick_id, motivo, tentativas, ultima_tentativa_em)

-- Controle de quota de API externa
api_quota (id, provedor, mes_referencia, chamadas, limite, atualizado_em)

-- Palpites
sources (id, nome, tipo, endpoint, ativo, quarentena, config_json, ultimo_sucesso_em)
  -- tipo: site | telegram | manual | rss
  -- quarentena: se true, os palpites são coletados e liquidados mas NUNCA entram no slate

raw_picks (id, source_id, texto_bruto, url_origem, autor,
           publicado_em, coletado_em, hash_conteudo UNIQUE)

picks (
  id, raw_pick_id, bloco_id, fixture_id,
  mercado, selecao, linha,
  odd_citada, casa_id, odd_coletada_em,
  odd_referencia, odd_referencia_origem, odd_referencia_em,
  odd_minima,            -- calculada para TODOS, sombra quando não publicado
  confianca_tipster,     -- confiança DECLARADA pela fonte (unidades, stake sugerido)
  stat_fonte,            -- estatística DERIVADA pela fonte (ex: % dos últimos jogos)
  stat_fonte_tipo,       -- descrição do que a estatística mede
  tipster,
  status,              -- extraido | vinculado | revisao_manual | descartado | sem_odd
  score_matching, extraido_em
)

-- Usuários e assinatura
users (id, nome, telefone_e164, fuso_horario, idioma,
       opt_in_em, opt_in_origem, opt_out_em,
       status)          -- ativo | inadimplente | cancelado | pausado

subscriptions (
  id, user_id,
  inicio, fim,            -- período pago
  valor, meio_pagamento,  -- pix | transferencia | outro
  referencia_pagamento,   -- id da transação, para conferência manual
  registrado_em, registrado_por
)

user_preferences (user_id, ligas_excluidas[], mercados_excluidos[],
                  odd_min, odd_max, max_msgs_dia, horario_envio)
  -- opcional. Padrão é receber tudo. Preferência só subtrai, nunca adiciona

-- Fila de envio
messages (id, user_id, fixture_id, pick_ids[],
          corpo_renderizado,
          status,            -- pronta | enviada | pulada | expirada
          idempotency_key UNIQUE,
          gerada_em, enviada_em, motivo_pulo)

-- Liquidação: resultado de cada palpite, independente de envio
pick_results (
  id, pick_id UNIQUE, fixture_id,
  resultado,          -- green | red | meio_green | meio_red | void | nao_liquidavel
  resolver,           -- qual resolver decidiu (ex: over_under_v1)
  evidencia_json,     -- placar e stats usados na decisão, para auditoria
  liquidado_em, revisado_por_humano
)

-- Banca simulada: um extrato por usuário, append-only
user_bankroll_config (user_id, banca_inicial, stake_pct,
                      modo_stake,   -- fixo (sobre banca inicial) | proporcional (sobre banca atual)
                      iniciado_em)

bets (
  id, user_id, message_id, pick_id, fixture_id,
  odd, stake_valor, stake_pct,
  resultado, retorno,
  banca_antes, banca_depois,
  sequencia,          -- posição do usuário no extrato, para ordenação determinística
  registrado_em, liquidado_em
)
```

Regra de ouro do extrato: `bets` é append-only e a banca atual é sempre recalculada dobrando o extrato do início, nunca lida de um campo mutável. Se uma liquidação for corrigida, o recálculo a partir daquele ponto resolve tudo.

Índices: `fixtures(kickoff_utc, status)`, `team_aliases.alias_normalizado`, `messages(status, gerada_em)`.

Note que **não existe tabela de odds**. A odd vive em `picks.odd_citada`, vinda do texto do próprio tipster. Explicação na Fase 1.

## Critérios de aceite

- `make setup` sobe o banco e roda as migrations
- `make test` passa
- `CLAUDE.md` descreve como rodar tudo

---

# Fase 1: Dados de partidas via ESPN

## Por que só a ESPN

A ESPN cobre bem o que preciso: partidas, times, horário, status, estádio, placar. O que ela cobre mal é odds, e eu decidi não usar odds de API nenhuma.

Motivo: a odd que interessa ao usuário é a que o tipster viu quando fez o palpite, e ela já vem no texto do palpite. Odd puxada de API envelhece em minutos e cria uma promessa que o site da casa não cumpre. Vou exibir a odd citada pela fonte, com o horário da coleta e um aviso de que pode ter variado. Não há link de afiliado no produto: o modelo é assinatura mensal paga, então a casa aparece apenas como referência de onde aquela cotação foi vista.

Isso elimina um provedor inteiro, uma chave de API, um limite de requisições e toda a reconciliação de IDs entre dois sistemas.

## Endpoints

```
GET https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/scoreboard?dates=YYYYMMDD
GET https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/summary?event={id}
GET https://site.api.espn.com/apis/site/v2/sports/soccer/{liga}/teams
```

Códigos de liga: `bra.1`, `bra.2`, `bra.copa_do_brazil`, `eng.1`, `esp.1`, `ita.1`, `ger.1`, `fra.1`, `uefa.champions`, `conmebol.libertadores`, `conmebol.sudamericana`.

## Fase 1a: sonda antes de implementar

Antes de escrever o coletor, escreva um script descartável que chame o `scoreboard` e o `summary` para 3 partidas do Brasileirão e 2 da Champions e me mostre o JSON completo. Quero que você me responda com base no retorno real, não com base em suposição:

1. Quais campos de horário existem e em que fuso vêm
2. O que exatamente tem em `broadcasts` e `geoBroadcasts`, e se aparece alguma emissora brasileira
3. Se existe bloco de odds no retorno e, se existir, quais casas e quais mercados
4. Quais campos são estáveis entre partidas e quais aparecem só às vezes
5. Se `sports.core.api.espn.com` traz algo relevante que o `site.api` não traz

Essa API é interna do site da ESPN, sem documentação oficial e sem contrato de estabilidade. Trate quebra de schema como caso esperado: valide com pydantic, logue divergência e siga, nunca derrube o pipeline.

## Transmissão

Se a sonda confirmar que os dados da ESPN são enviesados para os EUA, use a tabela `broadcast_rules` como fonte primária para o Brasil. Eu preencho na mão o mapeamento de liga, mandante e dia da semana para os detentores de direitos. A ESPN entra como complemento quando trouxer algo útil.

## Matcher de partidas

O módulo mais importante da fase. A ESPN chama de "Atlético Mineiro", o tipster escreve "Galo".

1. **Normalização:** minúsculas, remoção de acentos, remoção de sufixos (`FC`, `EC`, `SC`, `CF`, `AC`, `-MG`, `/SP`), colapso de espaços
2. **Match exato** contra `team_aliases.alias_normalizado`
3. **Fuzzy match** com `rapidfuzz.token_set_ratio`, threshold 85
4. **Janela temporal:** kickoff ±36h para desambiguar
5. **Abaixo do threshold:** vai para fila de revisão manual, não chuta
6. **Aprendizado:** todo match aprovado manualmente vira alias novo

Popule `team_aliases` inicialmente com os nomes vindos do endpoint `/teams` da ESPN, que já traz nome completo, nome curto, abreviação e apelido.

CLI: `python -m app.matcher review` lista pendências e me deixa aprovar ou rejeitar.

## Coleta de resultados

Além das partidas futuras, o sistema precisa fechar as partidas passadas. Job separado que roda a cada 30 minutos e busca fixtures com `status != encerrada` e kickoff há mais de 2 horas.

Do `summary` extraia: placar final, placar do intervalo, e o bloco de estatísticas por time (escanteios, cartões, finalizações, posse). Grave em `fixture_stats` marcando a origem.

Na sonda da Fase 1a, inclua três perguntas a mais e me responda com base no retorno real:

6. O `summary` traz estatísticas de escanteios e cartões para Brasileirão Série A, Série B e Champions
7. Quanto tempo depois do apito final o placar aparece como definitivo
8. Como a ESPN marca partida adiada, cancelada e suspensa

Partida adiada ou cancelada deve marcar todos os palpites vinculados como `void`, não como derrota.

## Odd de referência: capturada na coleta, não na curadoria

**Todo palpite recebe odd de referência e odd mínima assim que é vinculado a uma partida**, mesmo os que nunca vão entrar num slate: fontes em quarentena, palpites cortados pelo filtro de conflito, palpites que eu removi na curadoria.

Isso não é detalhe de implementação. Sem odd, um palpite liquidado só produz taxa de acerto, e taxa de acerto isolada é justamente a métrica enganosa que este sistema existe para desmontar. Uma fonte com 89% de acerto em odds de 1.25 tem ROI de menos 11%. Se o relatório de fontes não conseguir calcular ROI, ele repete o erro que deveria expor.

Consequências no fluxo:

- A odd é capturada logo após o matching com a ESPN, na Fase 1, não na Fase 4
- `odd_minima` é calculada pela mesma fórmula para todos, virando **odd mínima sombra** para os que não forem publicados. A comparação entre fonte publicada e fonte em quarentena precisa ser feita sobre a mesma base
- Palpite sem odd de referência é marcado `sem_odd` e fica fora de qualquer cálculo de ROI, aparecendo como pendência no relatório. Nunca entre num cálculo com odd estimada
- Na curadoria, a odd já está lá. Eu só edito quando estiver faltando ou visivelmente errada

### Hierarquia de origens

1. **Da própria fonte, quando a casa citada é licenciada no Brasil.** É o caso do SDA, que cita Superbet, Betano, bet365, Novibet, BetBoom e VBET. Nenhuma chamada de API, nenhum custo
2. **Do OddsPapi**, quando a fonte cita casa não licenciada (Eagle Predict, Andy Robson) ou não cita odd nenhuma (APWin)
3. **Digitada na curadoria**, quando as duas anteriores falham. Só vale para palpite que vai ao ar

Grave sempre a origem em `odds_referencia.origem`. No relatório de fontes, a diferença sistemática entre a odd citada por uma fonte e a odd de referência independente diz se aquela fonte infla números.

### Como a quota fecha mesmo puxando odd para tudo

Puxar odd por palpite individual estouraria as 250 requisições mensais. A solução é a mesma para todas as fontes que precisam do OddsPapi:

1. Restrinja o conjunto de ligas a 4 a 6 torneios com cobertura confirmada de ESPN e OddsPapi. Palpite fora dessas ligas é descartado na entrada, com contagem registrada
2. Uma chamada diária de `/odds-by-tournaments` por casa cobre **todas as partidas** desses torneios, publicadas ou não
3. Custo: 1 a 3 requisições por dia, 30 a 90 por mês

Repare que a chamada em lote é indiferente ao destino do palpite. A mesma requisição que serve o slate serve a quarentena, o que resolve os dois problemas com um único custo.

## OddsPapi: complemento, não fundação

Com a hierarquia acima, o OddsPapi cobre a lacuna, não o caso base.

### Contrato

```
Base: https://api.oddspapi.io/v4
Autenticação: parâmetro de query `apiKey`, NÃO header. Isso é incomum, atenção.
Formato: sempre passar oddsFormat=decimal
```

Endpoints relevantes:

| Endpoint | Uso |
|---|---|
| `/bookmakers` | descobrir os slugs reais das casas brasileiras. Chamar uma vez e cachear |
| `/tournaments` | pegar `tournamentId` das ligas. Chamar uma vez e cachear |
| `/odds-by-tournaments?bookmaker=X&tournamentIds=17,8` | **o principal.** Lote de partidas com odds |
| `/odds?fixtureId=X` | uma partida específica, para conferência pontual |
| `/settlements?fixtureId=X` | resultado por mercado, ver 6a |
| `/historical-odds?fixtureId=X&bookmakers=a,b` | máximo 3 casas. Suporta ETag e If-None-Match |

### Orçamento de requisições

Tier gratuito: **250 requisições por mês**, cerca de 8 por dia. Isso é restrição de projeto, não detalhe.

Regras obrigatórias:

- **Nunca chame `/odds` por partida em loop.** Use `/odds-by-tournaments` com todos os `tournamentIds` ativos numa chamada
- Uma chamada por dia por casa. Com duas ou três casas, são 60 a 90 por mês e sobra folga
- `/bookmakers` e `/tournaments` são estáticos. Cacheie em tabela, revalide uma vez por mês
- Grave cada chamada em `api_quota`. Ao atingir 80% do limite mensal, bloqueie chamadas não essenciais e me avise no health check
- Respeite o cooldown de 5 segundos entre chamadas ao mesmo endpoint
- Onde a API suportar ETag, use `If-None-Match`

### Mapeamento de ligas e partidas

Terceiro sistema de ids no projeto. A tabela `league_map` liga o código de liga da ESPN ao `tournamentId` do OddsPapi. Eu preencho na mão uma vez, são poucas linhas e mudam raramente.

Para partidas, estenda o matcher que você já vai construir: nomes de times mais janela de kickoff de ±36h, gravando `oddspapi_fixture_id` no `fixtures`. Partida sem match não impede nada, só fica sem odd de referência e é sinalizada na curadoria.

### Verificação antes de implementar

Antes de escrever o adapter, pegue a chave gratuita e responda com dados reais:

1. Quais slugs de casas brasileiras existem de fato em `/bookmakers`, e se `superbet` e `bet365` aparecem com entidade brasileira
2. Se o Brasileirão Série A e B têm `tournamentId` e cobertura real de odds
3. Quais mercados vêm por casa: 1x2, dupla chance, over/under, ambas marcam, handicap, escanteios
4. Como os ids numéricos de mercado e de outcome se mapeiam para os mercados que a gente usa. Monte uma tabela de tradução e documente
5. Quantas requisições uma execução completa consome de verdade

Se a cobertura brasileira não corresponder ao que o material de marketing deles promete, me diga antes de eu pagar qualquer coisa. Nesse caso a alternativa é entrada manual, ver Fase 4.

## Cache e educação com a API

A ESPN não cobra nem publica limite, o que não é licença para abusar. Cache em Postgres com TTL de 6h antes do jogo e 30min durante. Uma requisição por liga por dia, nunca uma por partida. User-Agent identificável. Rate limit de 1 requisição por segundo.

## Critérios de aceite

- Comando único popula partidas de 7 dias para as ligas configuradas
- Sonda documentada no `CLAUDE.md` com o que a ESPN realmente entrega
- Fila de revisão manual funcionando
- Rodar duas vezes seguidas não duplica partida

---

# Fase 2: Coletores de palpites

## Fonte 1: Eagle Predict (já investigada)

Essa fonte já passou pelo reconhecimento. Implemente com a spec abaixo, sem repetir a investigação.

```
Nome: Eagle Predict
Tipo: telegram_publico
Endpoint: https://t.me/s/eaglepredict
Idioma: inglês
Volume: cerca de 4 palpites por dia, num post único
```

**Estratégia: HTML, sem Telethon.** O canal é público e o Telegram serve uma versão renderizada no servidor em `t.me/s/{canal}`. Use `httpx` mais `beautifulsoup4`. Sem sessão, sem conta, sem API. O adapter de Telethon fica reservado para canais que não tenham essa versão.

**Paginação:** os parâmetros `?before={id}` e `?after={id}` navegam pelo histórico usando o id da mensagem. Na primeira execução, faça backfill de 90 dias para ter base de liquidação histórica. Depois, incremental com `?after={ultimo_id_visto}`.

**Identificação do post útil:** só interessa post que contenha o marcador de bloco de palpite (`Football Betting Tip`). Descarte enquete, áudio, pedido de compartilhamento, retrospectiva de acerto e teaser que só linka para o site. Espere que a maioria dos posts caia fora, isso é normal.

**Formato do bloco**, repetido 4 vezes por post:

```
⚽ Football Betting Tip ⚽
Date: 11/3/2024
League: English Premier League
Match: Chelsea VS Newcastle Utd
Kick off: 21:00 WAT
✅ DOUBLE CHANCE: 12
✅ Odds @1.24 on 1XBET
```

Mesmo sendo estruturado, mantenha o princípio da Fase 2: capture o texto do post inteiro e deixe a extração para o modelo na Fase 3. Não escreva regex para os campos. O canal muda o layout de tempos em tempos e o modelo absorve isso.

**Fuso horário: WAT, que é UTC+1.** Converta para UTC na gravação. Para BRT são 4 horas de diferença. Escreva teste específico para essa conversão, incluindo virada de dia. Errar aqui coloca horário errado em toda mensagem enviada.

**Formato de data: D/M/YYYY**, dia primeiro. Não confunda com M/D.

**Ignore a casa de aposta citada.** As odds vêm de 1XBET, PARIMATCH e BETBONANZA, que em geral não são autorizadas a operar no Brasil. Grave `casa_id` como referência interna para auditoria, mas **nunca renderize o nome da casa no template para o assinante** quando ela estiver marcada como `ativa = false` na tabela `casas`. A mensagem mostra mercado, seleção e odd citada, e o assinante escolhe onde apostar. Torne isso uma regra do renderizador, não uma configuração.

**Nomes de times em inglês.** Vantagem: a ESPN também usa inglês, então o matching fica direto. Popule os aliases a partir do endpoint `/teams` da ESPN antes de rodar o primeiro backfill.

**Cobertura de ligas:** Premier League, La Liga, Serie A, Bundesliga, Champions, Europa League, Primeira Liga, Championship inglês, Turquia, divisões menores da Holanda. Nenhuma liga brasileira. Configure as ligas da ESPN levando isso em conta.

**Perfil dos palpites:** odds concentradas entre 1.20 e 1.40, mercados de dupla chance, over 1.5 e DNB. Estratégia de favorito pesado. Isso importa para a Fase 6: numa faixa dessas, taxa de acerto alta convive tranquilamente com ROI negativo. O relatório por fonte precisa mostrar ROI ao lado da taxa de acerto sempre, nunca só a taxa.

## Fonte 2: Sites de Apostas (SDA), já investigada

```
Nome: Sites de Apostas
Tipo: site
Listagem: https://www.sites-de-apostas.net/prognosticos-noticias/category/prognosticos-de-apostas
Paginação: /page/{n}, arquivo com milhares de páginas
Plataforma: WordPress
Idioma: português do Brasil
```

**Essa fonte já traz odd e casa licenciada no Brasil junto do palpite.** É a origem preferencial de `odd_referencia`, à frente do OddsPapi.

### Estratégia

Antes de escrever o parser de HTML, teste `/wp-json/wp/v2/posts`. O site é WordPress. Se o REST expuser os campos do card (mercado, odd, casa), use a API. Se os dados estiverem em campos customizados não expostos, o que é provável, caia para HTML com `httpx` mais `beautifulsoup4`. A listagem é renderizada no servidor, não precisa de Playwright.

### Campos do card na listagem

| Campo | Observação |
|---|---|
| Liga | **não confie no link de categoria.** Extraia do título. Ver armadilha abaixo |
| Tipster | nome e URL de autor. **Dois padrões de URL coexistem:** `/autores/{slug}` e `/author/{slug}` |
| Partida | do título, formato `Palpite {casa} x {fora} – {liga} – {DD/MM/AAAA}` |
| Data | formato DD.MM.AAAA. Pode vir vazio |
| Horário | HH:MM, horário de Brasília. Pode vir vazio |
| Status | rótulo "Começa em" para ativo, "Terminado" para encerrado |
| Mercado, seleção, odd e casa | tudo numa string única, ver abaixo. Pode vir vazio |
| URL do post | slug padronizado, chave de deduplicação |

### Armadilhas confirmadas por amostragem

Estas foram verificadas nas páginas 1 e 2 da listagem. Não assuma nada além do que está aqui sem checar.

**Existem pelo menos dois formatos de card, coexistindo na mesma página:**

```
Formato A:  Ambas as equipes marcam: sim 2.12 Betano
Formato B:  Menos 2.5 gols, - odds 1.57 1.57 SuperbetSuperbet
```

No formato B a odd aparece duplicada. O nome da casa também pode duplicar. **As duas duplicações são independentes**: existe o caso "Mais 2 gols, - odds 1.75 1.75 Betano", com odd dobrada e casa simples.

Parece haver correlação com o autor, mas não de forma confiável. Não escreva o parser assumindo formato. Extraia a string inteira, normalize as repetições literais adjacentes, e deixe a Fase 3 estruturar.

**Redação do mercado varia muito.** Observados para estruturas equivalentes: "Mais de 1.5 gols", "Mais 2 gols", "Mais 1.5 gols", "Menos 2.5 gols, - odds", "Menos de 2.5 gols", "Ambos os times marcam, - sim - odds", "Ambas as equipes marcam: sim". Nunca regex por mercado.

**Linhas asiáticas quebradas em gols.** Apareceram "Mais 2.75 gols" e "Menos 2.25 gols", em casas diferentes, então não é anomalia de uma casa. Isso divide a aposta em duas metades e produz meio-green e meio-red. O resolver de over/under da Fase 6 **precisa** tratar linhas .25 e .75, não só .5 e inteiras. Isso não era esperado e é onde o cálculo da banca erra silenciosamente.

**A paginação aparece duas vezes no HTML, e as duas são independentes.** A página tem duas abas, "Palpites ativos" e "Jogos encerrados", ambas renderizadas no mesmo documento, ambas usando `/page/N`, **com totais diferentes**. Nas amostras, a aba de ativos terminava na página 4 enquanto a de encerrados listava 5.845.

Consequência: um coletor que lê o número maior e itera atrás de palpites ativos roda milhares de páginas vazias. Identifique a aba pelo rótulo do card ("Começa em" ou "Terminado"), nunca pela posição no documento nem pelo bloco de paginação.

**A liga do link de categoria não é confiável.** Foi observado o post "Palpite Inter Miami CF x Columbus Crew – MLS – 01/08/2026" categorizado como Copa Argentina, inclusive com `copa-argentina` no slug. Título, categoria e slug divergem.

Ordem de precedência para a liga: título do post, depois slug, depois categoria. E o matching com a partida da ESPN é o desempate final. Se a liga inferida não bater com a liga da fixture encontrada, mande para revisão manual em vez de aceitar.

**Existem cards estruturalmente vazios, e isso é sistemático por autor.** Nas amostras, todos os posts de um autor específico (Fabio Storino) vinham sem horário, sem odd, sem casa, com o bloco de palpite literalmente vazio. Ele publica análise em prosa sem preencher os campos do card.

O parser precisa tolerar campo vazio sem quebrar. Card sem odd e sem mercado **não vira `pick`**, vira `raw_pick` marcado como `sem_palpite_estruturado`, para não sujar a métrica de saúde da fonte. Se um autor produzir mais de 80% de cards vazios, sinalize para eu decidir se filtro esse autor na coleta.

**Duas convenções de URL de autor.** `/autores/{slug}` e `/author/{slug}` coexistem. Aceite as duas.

**Links de paginação carregam `?utm_campaign=palpite`** a partir da terceira página. Normalize removendo query string antes de usar qualquer URL como chave.

**O slug do post nem sempre reflete o título.** Exemplo observado: título "Anderlecht x Hammarby – Liga Europa" com slug contendo `qualificatorias-liga-europa`. Use o slug só como chave de deduplicação, nunca como fonte de dado.

**Separador decimal misto.** Odds com ponto (1.62). Linhas com vírgula ("Mais de 9,5 escanteios cobrados", "Mais de 4,5 cartões mostrados", "Handicap -1,5 Palmeiras"). Mas "Mais 2.75 gols" usa ponto na linha. O separador varia dentro do mesmo tipo de campo. Normalize os dois casos.

**A ordem não é cronológica linear.** Ativos vêm por kickoff crescente, encerrados por kickoff decrescente. Um mesmo jogo pode aparecer em mais de uma página, e o "Palpite em Destaque" do topo repete um post da lista. Deduplique sempre pela URL do post, sem query string.

**Faixa de odds observada:** 1.44 a 2.45.

### Mercados observados nas amostras

Use esta lista para dimensionar os resolvers da Fase 6. Não é exaustiva.

| Mercado | Resolvível pela ESPN |
|---|---|
| Ambas as equipes marcam (sim/não) | sim, trivial |
| Over/Under gols, linha .5 | sim |
| Over/Under gols, linha .25 e .75 | sim, com meio-green e meio-red |
| Dupla chance ("X para ganhar ou empatar contra Y") | sim |
| Handicap inteiro ("Handicap -1 Atlético-MG") | sim, com void na margem exata |
| Handicap .5 ("Handicap -1,5 Palmeiras") | sim |
| Total de escanteios ("Mais de 9,5 escanteios cobrados") | depende de cobertura de stats |
| Total de cartões ("Mais de 4,5 cartões mostrados") | depende de cobertura de stats |
| Cartões por time ("Ambas as equipes recebem 2 cartões ou mais") | depende de stats por time, resolver próprio |

Note que total de cartões e cartões por time são mercados diferentes e precisam de resolvers separados. O segundo exige que a condição valha para os dois times simultaneamente.

### Escopo: dois modos de coleta

**Modo recorrente (padrão).** Colete somente os cards com rótulo "Começa em". Descarte tudo com "Terminado". Uma paginação só, cerca de 4 páginas por execução, sem regra de parada por data.

A regra de parada é por conteúdo, não por número: pare quando uma página não trouxer card novo com rótulo "Começa em". O número de páginas da aba ativa varia com o volume de jogos, e numa rodada de meio de semana pode dobrar.

**Modo backfill (executado uma vez, na largada).** Comando separado, `python -m app.collectors backfill --source sda --dias 90`, que percorre a aba de encerrados para construir a base histórica de liquidação.

Isso é etapa obrigatória antes do primeiro slate pago. Sem ela, você só descobre o ROI real da fonte depois de 90 dias de operação. Com ela, entra sabendo.

Regras do backfill:

- Parada por data: percorra até a data mais antiga do lote ultrapassar 90 dias. Nas amostras, cada página cobria de 2 a 3 dias, então espere entre 30 e 50 páginas
- Rate limit de 1 requisição a cada 3 segundos. São poucos minutos no total
- Grave `raw_picks.origem_coleta = 'backfill'` para eu conseguir separar depois
- Espere estrutura de HTML diferente conforme recua no tempo. Card que não parsear no formato conhecido vai para revisão manual, não derruba a execução
- Não estenda além de 90 dias. Posts mais antigos provavelmente usam layout antigo e o retorno cai rápido
- Rode uma vez e não agende. Repetir o backfill só duplica trabalho, já que a deduplicação por URL barra tudo

Depois do backfill, a aba de encerrados sai do fluxo. Todo palpite novo entra pelos ativos e é liquidado pelo seu próprio motor quando o jogo terminar.

### Ligas e escopo

Cobre Brasileirão Série A, B, C e D, Copa do Brasil, Libertadores, Sul-Americana, Argentino, Champions, Europa League, Premier League, La Liga, Serie A, Bundesliga, Ligue 1, Eredivisie, Championship, Português, Turco e Chileno.

Também publica NBA, NFL, UFC e eSports. **Filtre apenas futebol** na coleta, o resto não entra no escopo do produto.

### Casas citadas

Superbet, Betano, bet365, Novibet, BetBoom e VBET. Todas licenciadas no Brasil, com número SPA/MF publicado. Cadastre todas com `licenciada_br = true` e `ativa = true`.

Isso torna a odd citada por essa fonte utilizável diretamente como `odd_referencia`, o que não vale para a Eagle Predict.

### Tipsters nomeados

Cada palpite tem autor identificado com página própria. Grave `tipster` e a URL do autor. O relatório da seção 6d deve permitir agrupar por tipster, não só por fonte: saber que um autor performa bem na Série C e mal na Série D é informação acionável na curadoria.

### Fuso horário

Horário já em Brasília. Converta para UTC na gravação, sem a complicação do WAT da Eagle Predict.

### Nota de escopo

Essa fonte pertence a um grupo concorrente e distribui os mesmos palpites gratuitamente em canal próprio de WhatsApp. Ela é insumo de análise e origem de odd de referência, **não a espinha dorsal do produto**. O slate nunca deve ser majoritariamente composto por uma única fonte externa. Implemente um limite configurável de participação por fonte no slate diário, com padrão de 50%.

Formato mínimo. Não descreva a estrutura da página, o script de reconhecimento descobre isso sozinho. Me diga só o que ele não tem como saber:

```
1. Nome: Blog Tal
   Tipo: site
   URL da listagem: https://exemplo.com/palpites
   URL de um post exemplo: https://exemplo.com/palpites/jogo-x-hoje
   Onde estão os palpites: no corpo do post, geralmente 3 a 5 por publicação
   Ignorar: barra lateral com "mais lidos", box de promoção no fim
   Exige login: não
   Frequência de publicação: diária, por volta das 9h BRT

2. Nome: Canal Palpites XYZ
   Tipo: telegram
   Username: @canal_xyz
   Sou membro: sim
```

A linha "onde estão os palpites" e a linha "ignorar" são as únicas que realmente importam, porque são julgamento editorial que só eu tenho.

## Fase 2a: reconhecimento antes de implementar

Não escreva coletor nenhum antes de olhar as páginas. Crie um script de diagnóstico:

```
python -m app.recon https://exemplo.com/palpites
```

Para cada URL, o script investiga e me devolve um relatório:

1. **Existe feed RSS ou Atom?** Cheque `<link rel="alternate">` no `<head>`, e os caminhos comuns (`/feed`, `/rss`, `/feed.xml`)
2. **É WordPress?** Se sim, teste `/wp-json/wp/v2/posts` e me diga se responde e com quais campos
3. **Existe endpoint JSON alimentando o front?** Abra com Playwright, capture as requisições XHR e liste as que devolvem JSON com conteúdo relevante
4. **Existe JSON-LD ou microdata** no `<head>` com dados do artigo
5. **O conteúdo aparece no HTML inicial ou só depois do JavaScript?** Compare o retorno do `httpx` com o do Playwright
6. **Existe sitemap** em `/sitemap.xml` ou `/sitemap_index.xml`, e ele lista os posts por data
7. **O que diz o `robots.txt`** sobre os caminhos que interessam
8. **Existe paginação, e de que tipo:** links numerados, scroll infinito, botão "carregar mais"

Termine o relatório com uma recomendação de estratégia, escolhida nesta ordem de preferência:

```
RSS  >  API REST  >  JSON-LD  >  XHR interceptado  >  HTML + httpx  >  HTML + Playwright
```

Só depois que eu ler o relatório de todas as fontes é que você implementa os adapters.

## Princípio de extração: scraper burro, modelo inteligente

O coletor **não** deve tentar extrair mercado, seleção, odd ou casa do HTML. Isso é trabalho da Fase 3.

A responsabilidade do coletor é mínima:

- Encontrar a lista de publicações novas
- De cada publicação, capturar o bloco de texto principal, a URL, o autor e a data
- Gravar em `raw_picks`

Um seletor genérico de corpo do artigo (`article`, `.post-content`, `main`) sobrevive a redesign muito melhor que cinco seletores precisos apontando para campos individuais. Prefira sempre o seletor mais grosseiro que ainda isole o conteúdo do menu, rodapé e barra lateral.

Se um site publicar os palpites já em tabela estruturada, ainda assim capture o bloco inteiro como texto e deixe a extração para o modelo. Um caminho só de extração é mais fácil de manter e testar que dois.

## Detecção de quebra

Todo adapter precisa declarar um baseline: quantas publicações essa fonte costuma render por execução. Se uma execução devolver zero, ou menos de 30% do baseline móvel dos últimos 10 dias, marque como suspeita e me avise. Scraper que quebra silenciosamente e devolve lista vazia é o modo de falha mais comum e mais caro desse tipo de sistema.

Guarde o HTML bruto da última execução bem-sucedida de cada fonte. Quando quebrar, o diff entre o HTML antigo e o novo mostra o que mudou em segundos.

## Fonte 3: Andy's Bet Club, com decomposição, em QUARENTENA

Implementar. O conteúdo dele é quase todo múltipla, então a regra central é **decompor e descartar o combo**.

```
Nome: Andy's Bet Club (Andy Robson)
Listagem: https://andysbetclub.co.uk/tips/football/ (aba "All")
Palpite simples: https://andysbetclub.co.uk/tips/football/bet-of-the-day/
Por partida: https://andysbetclub.co.uk/football-fixtures/{casa}-v-{fora}-{AAAAMMDD}/tips/
Idioma: inglês
Escopo: apenas futebol. Ignore horse racing, darts, NFL, boxing
```

**Não use o X.** O perfil @AndyRobsonTips é vitrine, não fonte. O site é a origem canônica, com conteúdo renderizado no servidor, e os palpites saem lá pelo menos 24h antes do kickoff. Coletar do site elimina a necessidade de API paga do X e o problema de termos de uso.

### Decomposição: a regra central

Nunca grave a múltipla como palpite. Quebre cada acumulada, dupla e bet builder nas pernas individuais. Cada perna vira um `pick` separado.

```sql
pick_blocos (id, source_id, tipo, odd_combinada, url_origem, coletado_em)
  -- tipo: acumulada | dupla | bet_builder | outright | simples
```

Cada `pick` gerado guarda `bloco_id` e a posição dentro do bloco. Isso permite depois comparar o desempenho das pernas com o do combo original, que é informação de curadoria.

**A odd combinada é descartada para efeito de cálculo.** Ela não se aplica a nenhuma perna isolada. Guarde em `pick_blocos.odd_combinada` só para auditoria.

**Cada perna precisa de odd própria, vinda do OddsPapi.** A página publica apenas a odd do combo. Isso multiplica o consumo de quota, então vale a mesma solução da quarentena do APWin: restrinja as ligas a um conjunto com cobertura confirmada de ESPN e OddsPapi, e puxe odds em lote com `/odds-by-tournaments` uma vez por dia.

**Filtro de mercado na entrada, antes da extração.** Só aceite pernas cujos mercados tenham resolver implementado:

| Aceitar | Descartar |
|---|---|
| Resultado final (1x2) | Props de jogador (faltas, chutes, cartão de fulano) |
| Dupla chance | Escanteios de um time específico |
| Ambas marcam | Cartões de um time específico |
| Over/under gols | Outrights de temporada |

Perna descartada não vira `raw_pick` nem consome chamada de odd. Registre a contagem de descarte por tipo de mercado, para eu saber quanto do conteúdo dele sobra depois do filtro.

### Por que quarentena

A reputação dele vem de acumulada batendo. Perna individual é uma métrica diferente e desconhecida: pode ser melhor ou pior que o combo. Sessenta dias de liquidação respondem isso antes de qualquer assinante ver o palpite.

### Fonte alternativa de palpite simples

`https://andysbetclub.co.uk/tips/football/bet-of-the-day/` publica aposta única, sem decomposição e sem filtro de mercado. Colete essa página como um coletor separado, com sua própria linha em `sources`, para eu conseguir comparar o desempenho do palpite único dele contra as pernas decompostas.

### Requisitos técnicos

**Formato de odd.** O site tem alternador decimal e fracionário. Force decimal e valide, porque conteúdo antigo e o perfil no X usam fracionário (5/6, 12/1).

**Estrutura técnica.** Site em Next.js com CMS headless em `cms.andysbetclub.co.uk`. Antes de parsear HTML, procure o endpoint JSON que alimenta o front, seguindo a Fase 2a. Provavelmente existe e é muito mais estável.

**Ligas.** Escocesa, Eredivisie, Belga, Suíça, Norueguesa, Sueca, League One, League Two, EFL Cup, Premier League, Champions. Confirme cobertura da ESPN antes de aceitar cada uma.

**Casas citadas.** Paddy Power, Betfair, SkyBet, William Hill, Virgin Bet, Dabble. Só a bet365 tem licença brasileira, então vale a mesma regra do renderizador: casa com `ativa = false` não aparece na mensagem.

**Mesma ressalva competitiva do SDA.** Ele também distribui gratuitamente, inclusive por canal de WhatsApp próprio. Vale o mesmo limite de participação por fonte no slate.

## Fonte 4: APWin Decreasing Stats, em QUARENTENA

Colete, liquide, **mas não coloque no slate pago** até o relatório de 60 dias autorizar. Ver justificativa abaixo.

```
Nome: APWin Decreasing Stats
Tipo: site
Aba: Today
Filtro: apenas entradas com 100%
```

Sete páginas, cada uma corresponde a um mercado fixo. **O mercado vem da página, não do texto.** Isso dispensa a extração da Fase 3 para essa fonte, que passa direto de `raw_pick` para `pick` estruturado.

| URL | Mercado |
|---|---|
| `/decreasing-stats/` | ambas marcam |
| `/decreasing-stats/over-goals/` | over 2.5 gols |
| `/decreasing-stats/over-ht-goals/` | over 1.5 gols no primeiro tempo |
| `/decreasing-stats/over-corners/` | over 9.5 escanteios |
| `/decreasing-stats/over-45-team-corners/` | over 4.5 escanteios de um time |
| `/decreasing-stats/over-45-cards/` | over 4.5 cartões |
| `/decreasing-stats/team-over-25-cards/` | over 2.5 cartões de um time |

### Campos por linha

Data e hora, liga, time da casa e visitante com URL própria, percentual, e link `View Match` com id curto. Estrutura tabular limpa, sem as armadilhas de texto do SDA.

**Não traz odd nem casa.** Toda odd de referência precisa vir do OddsPapi.

### O que o percentual significa

O 100% do APWin **não é alegação de acerto**. É estatística derivada: nos últimos jogos das duas equipes, aquilo aconteceu em todas as ocorrências da janela de referência. É medida de forma recente, não promessa de resultado.

Grave em `stat_fonte`, com `stat_fonte_tipo = 'frequencia_ultimos_jogos'`. Não use o campo `confianca_tipster`, que é reservado para confiança declarada pela fonte, tipo unidades ou stake sugerido. Misturar os dois no relatório produziria comparação sem sentido entre coisas diferentes.

### Por que quarentena mesmo assim

Frequência recente alta e valor esperado positivo são coisas independentes. Ambas marcam é precificado pelas casas entre 1.60 e 2.00, implicando probabilidade entre 50% e 62%. Se o filtro de 100% capturasse informação que a casa não tem, isso seria vantagem real. Se for só reversão à média esperando acontecer, é armadilha.

Ninguém sabe qual dos dois sem medir, e foram observadas 16 partidas a 100% num único dia num único mercado, o que sugere janela de referência curta. A quarentena existe para responder isso com o próprio motor de liquidação, antes de qualquer assinante ver o palpite.

### Análise que a quarentena deve permitir

Além do ROI agregado, o relatório precisa cruzar `stat_fonte` com resultado. Se o percentual carregar informação, palpites de 100% devem performar diferente dos de 80%. Se não carregar, o ROI será estatisticamente indistinguível entre as faixas.

Colete também entradas abaixo de 100% para ter grupo de comparação. Sem isso você mede o desempenho do filtro, mas não descobre se o filtro faz alguma diferença.

### Regras de quarentena

Quarentena é um mecanismo geral, não específico do APWin. **Toda fonte nova entra com `quarentena = true` por padrão.** Sair da quarentena é decisão minha, tomada com relatório na mão, nunca configuração default.

- Colete e liquide normalmente, com `sources.quarentena = true`
- Palpite de fonte em quarentena **nunca** entra em `daily_slates`, nem por curadoria manual. O console não deve nem oferecer a opção
- Relatório semanal separado, com ROI e volume **por mercado**, não só por fonte
- Após 60 dias e mínimo de 200 palpites liquidados por mercado, gere o relatório de decisão. Eu decido mercado a mercado, não a fonte inteira
- Fonte que sai da quarentena entra no slate com teto de participação reduzido nos primeiros 30 dias

### Resolvendo o conflito entre volume e quota

O APWin pode gerar mais de 100 candidatos diários e não traz odd. Consultar odd individualmente estouraria as 250 requisições mensais do OddsPapi em dois dias.

A solução não é reduzir a amostra por sorteio, e sim **restringir as ligas da quarentena**:

1. Escolha de 4 a 6 torneios que tenham cobertura simultânea de ESPN (para placar e estatística) e OddsPapi (para odd). Confirme as duas coberturas antes de ligar a coleta
2. Colete do APWin apenas partidas dessas ligas, descartando o resto na entrada
3. Puxe odds com `/odds-by-tournaments` uma vez por dia, em lote, cobrindo todos esses torneios numa chamada por casa
4. Custo resultante: 1 a 3 requisições por dia, algo entre 30 e 90 por mês. Sobra folga

Isso resolve dois problemas de uma vez. A quota fecha, e a amostra fica concentrada em ligas onde a liquidação de fato funciona, em vez de dispersa em campeonatos cujo placar a ESPN não cobre e que virariam `nao_liquidavel` de qualquer jeito.

Registre quantas partidas foram descartadas por liga fora do escopo, para eu saber o tamanho do que ficou de fora.

### Restrições operacionais restantes

**Qualidade do feed.** Foi observado o confronto "Paksi SE v Honvéd Women", cruzando time masculino com feminino, o que indica erro na base deles. Divergência entre nome do time e competição vai para revisão manual, não vira dado válido.

**Site com paywall.** Tem login e sinais de conteúdo restrito. Se a coleta receber bloqueio ou conteúdo parcial, pare e me avise, não tente contornar.

**Mercados de primeiro tempo.** O over 1.5 HT exige placar do intervalo, previsto em `fixtures.placar_ht_casa` e `placar_ht_fora`. Confirme na sonda da ESPN que esse dado vem de fato, antes de aceitar essa página na coleta.

**Escanteios e cartões por time.** Quatro das sete páginas dependem de estatística por time, não de placar. Se a sonda da ESPN mostrar cobertura fraca disso nas ligas escolhidas, corte essas páginas da quarentena. Coletar palpite que nunca vai liquidar só polui o relatório.

**Sites:** um adapter por fonte, herdando de `BaseCollector`. `httpx` + `beautifulsoup4` primeiro, `playwright` só se a página exigir JS. Respeite `robots.txt`, User-Agent identificável, 1 requisição a cada 3 segundos por domínio, cache condicional com `ETag`/`If-Modified-Since`.

**Telegram:** primeiro teste se o canal tem versão pública em `t.me/s/{username}`. Se tiver, é HTML servido pelo servidor e resolve com `httpx` mais `beautifulsoup4`, sem conta e sem sessão. Só use `telethon` para canais privados ou sem preview público, guardando a sessão em arquivo fora do repositório.

**X:** a API oficial é paga e o scraping viola os termos de uso. Não implemente. Antes de descartar um tipster do X, procure o site próprio dele: tipsters grandes usam o X como vitrine e publicam o conteúdo completo num site que é a fonte canônica, coletável e mais estável. Foi o caso do Andy Robson. Se não houver site, entra pelo coletor manual.

**Manual:** CLI `python -m app.collectors manual` que abre um prompt onde eu colo o texto de um palpite e escolho a fonte. Grava em `raw_picks` como qualquer outro. É por aqui que entra qualquer coisa que o sistema não consegue coletar sozinho.

**Deduplicação:** hash SHA-256 do texto normalizado. Post já visto não vira `raw_pick` novo.

## Critérios de aceite

- Cada fonte roda isolada, falha de uma não derruba as outras
- Fonte com 3 falhas consecutivas fica inativa e aparece no log de saúde
- Rodar duas vezes seguidas não duplica nada

---

# Fase 3: Extração estruturada

Palpite vem em texto livre: "Galo vence hoje, odd boa na Bet365 @ 1.85, unidade 2".

API da Anthropic com `claude-sonnet-4-6`. Prompt com saída JSON estrita, sem markdown, sem preâmbulo:

```json
{
  "palpites": [{
    "time_casa": "string|null",
    "time_fora": "string|null",
    "competicao": "string|null",
    "data_referencia": "string|null",
    "mercado": "1x2|over_under|ambas_marcam|handicap|escanteios|cartoes|outro",
    "selecao": "string",
    "odd": "number|null",
    "casa_apostas": "string|null",
    "unidades": "number|null",
    "confianca_extracao": "number 0-1"
  }]
}
```

Regras:
- Um post pode conter zero, um ou vários palpites
- `confianca_extracao` abaixo de 0.7 vai para revisão manual
- Sempre preserve o `texto_bruto` original vinculado
- Batche vários posts por chamada, com limite de tokens por lote
- Cacheie por hash de conteúdo, nunca extraia duas vezes o mesmo texto
- Normalize `casa_apostas` contra a tabela `casas` usando os aliases

**Sobre o conteúdo coletado:** o texto original fica armazenado só como referência interna para extração e auditoria. As mensagens que eu envio usam apenas os dados estruturados mais texto de template próprio, nunca a redação original do tipster. Atribua a fonte quando ela for pública.

## Critérios de aceite

- 20 posts reais de exemplo, extração correta em pelo menos 85%
- Nenhum campo inventado. Ausente vira `null`
- Custo por 100 posts medido e documentado no `CLAUDE.md`

---

# Fase 4: Curadoria e templates

## Modelo de negócio

Assinatura mensal paga. Sem link de afiliado, sem comissão de casa. O que o assinante compra é curadoria mais histórico verificável de resultados. Isso muda três coisas em relação a um modelo de afiliação:

1. **Não existe personalização por preferência como filtro principal.** Quem paga espera receber a seleção completa, não um recorte. Todo assinante ativo recebe o mesmo conjunto de palpites do dia.
2. **A liquidação da Fase 6 deixa de ser diferencial e vira o produto.** É a única prova de que a assinatura vale o preço.
3. **A recomendação precisa ser coerente.** Dois palpites contraditórios na mesma partida, vindos de fontes diferentes, quebram a confiança de quem pagou.

## Stream único de palpites

Existe **uma** seleção diária, chamada `daily_slate`. O motor monta a lista uma vez, e cada assinante recebe a mesma coisa.

```sql
daily_slates (id, data, status, curado_em, curado_por)
slate_picks (
  id, slate_id, pick_id, ordem, incluido_por,
  odd_referencia,        -- capturada do OddsPapi ou digitada na curadoria
  odd_referencia_em,     -- timestamp da captura
  odd_minima,            -- o piso publicado ao assinante
  odd_minima_origem      -- calculada | manual
)
  -- incluido_por: automatico | manual
```

## Odd de referência e odd mínima

O produto não promete uma cotação. Promete um piso.

A mensagem informa a odd de referência como valor aproximado e declara a **odd mínima**: abaixo dela, o assinante não aposta, porque o retorno não paga o risco. É a única regra que não envelhece entre o envio e o kickoff.

### Cálculo do piso

```
odd_minima = max(
  odd_referencia * (1 - MARGEM_PCT),
  ODD_MINIMA_ABSOLUTA
)
```

Duas configurações, ambas ajustáveis sem deploy:

- `MARGEM_PCT`: quanto de queda é tolerável. Padrão 4%
- `ODD_MINIMA_ABSOLUTA`: piso de política. Padrão a definir, ver pergunta abaixo

O piso absoluto não é conta, é decisão de produto. Fontes como a Eagle Predict operam entre 1.20 e 1.40, e uma margem percentual sozinha produziria pisos de 1.15, onde a relação risco e retorno não justifica a entrada.

Arredonde sempre para baixo, em duas casas. Piso arredondado para cima quebra a promessa.

### Filtro de qualidade

Palpite cuja `odd_referencia` já esteja abaixo de `ODD_MINIMA_ABSOLUTA` **não entra no slate**. Não é um alerta na curadoria, é exclusão automática, com o motivo gravado. Se você não recomendaria a aposta, ela não vai para quem paga.

Na curadoria eu posso sobrescrever `odd_minima` manualmente para qualquer palpite, gravando `origem = manual`.

Montagem:

1. Filtra `picks` vinculados a fixtures com kickoff nas próximas 24h
2. Agrupa por fixture e detecta conflito: duas seleções mutuamente exclusivas no mesmo mercado da mesma partida
3. Em caso de conflito, mantém a de maior consenso entre fontes e marca a outra como `descartada_por_conflito`. Se houver empate no consenso, manda a partida inteira para revisão manual
4. Aplica limites globais configuráveis: máximo de palpites por dia, faixa de odd aceita, mercados sem resolver implementado ficam de fora
5. Gera o slate com status `rascunho`

**Curadoria manual obrigatória.** O slate só vira mensagem depois que eu aprovo no console. Posso remover palpite, reordenar e adicionar manualmente. Assinante pagante recebendo palpite automático sem revisão humana é risco que o preço da assinatura não cobre.

**Odd de referência na curadoria.** Cada item do slate mostra a odd de referência vinda do OddsPapi para as casas brasileiras configuradas, e a odd mínima calculada a partir dela. Se não houver referência (partida sem match, mercado sem cobertura, quota estourada), o campo fica editável e eu digito na mão consultando a casa. São poucos itens por dia, leva segundos.

Nenhum palpite entra no slate aprovado sem odd de referência e odd mínima definidas. Sem elas, a Fase 6 não consegue calcular banca honesta, e é melhor cortar o palpite do que registrar um número inventado.

Preferência de usuário existe, mas só subtrai: quem pediu para não receber Série B ou odds acima de 3.00 tem esses itens removidos do slate dele. Nunca adiciona nada que não esteja no slate.

## Controle de acesso

Antes de gerar qualquer mensagem, o motor verifica se o usuário tem assinatura cobrindo a data. Sem período válido, nenhuma mensagem é gerada. Usuário `inadimplente` some do console.

Como são no máximo 200 assinantes e o pagamento é conferido na mão (Pix), o registro é manual: `python -m app.subs registrar --user-id X --inicio 2026-08-01 --fim 2026-08-31 --valor 49.90 --ref "E12345..."`.

O console mostra um painel com assinaturas vencendo nos próximos 5 dias, para eu cobrar antes de cortar o acesso.

## Template

Jinja2, horário sempre convertido para o fuso do usuário.

```
Fala {{ primeiro_nome }}, olha o jogo de hoje:

{{ time_casa }} x {{ time_fora }}
{{ competicao }}
{{ horario_local }}
Onde assistir: {{ transmissao }}

Palpite: {{ selecao }}
Odd aproximada: {{ odd_referencia }}
Não aposte abaixo de {{ odd_minima }}
{% if fonte_publica %}Fonte: {{ fonte }}{% endif %}

{{ rodape_legal }}
```

Como o envio é manual e pessoal, o tom pode ser mais solto que o de uma mensagem de broadcast. Quero variação: crie 3 ou 4 saudações de abertura e sorteie, para não ficar com cara de robô quando a mesma pessoa recebe várias mensagens na semana.

O `rodape_legal` é obrigatório e configurável, com aviso 18+, jogo responsável e instrução de como sair da lista. Não torne esse campo opcional no código.

## Regras de negócio

- Idempotência: `idempotency_key = hash(user_id + fixture_id + data)`, constraint única. O mesmo usuário nunca recebe a mesma partida duas vezes
- Mensagem que passa do kickoff sem ser enviada vira `expirada` automaticamente
- Assinatura vencida durante o dia não invalida mensagem já enviada, mas bloqueia geração de novas
- Slate aprovado é imutável. Correção depois da aprovação gera um slate novo com referência ao anterior

## Critérios de aceite

- Rodar o motor duas vezes seguidas gera zero mensagens novas
- Usuário sem preferência configurada recebe o slate completo, não erro
- Usuário sem assinatura válida não gera nenhuma mensagem
- Conflito na mesma partida nunca chega ao assinante sem passar por decisão explícita
- Horário correto para usuários em fusos diferentes

---

# Fase 5: Console de controle

Uma aplicação FastAPI mais Jinja2 rodando em `localhost:8000`. Sem autenticação, sem deploy, só na minha máquina. Três abas.

## Sincronização: execução diária com etapas

Este é o coração operacional do sistema. **Não use crons independentes por tarefa.** Eles produzem estados parciais que ninguém percebe.

Cada dia gera uma `pipeline_run`, com etapas que avançam em ordem e registram resultado:

| Ordem | Etapa | O que faz | Se falhar |
|---|---|---|---|
| 1 | `fixtures` | ESPN, partidas das próximas 72h | bloqueia tudo |
| 2 | `coleta` | todas as fontes, em paralelo | degrada, segue com as que funcionaram |
| 3 | `extracao` | LLM estrutura o texto livre | degrada por fonte |
| 4 | `matching` | vincula palpite a partida | degrada, órfãos vão para fila |
| 5 | `odds` | OddsPapi em lote por torneio | degrada, palpites ficam `sem_odd` |
| 6 | `slate` | monta rascunho e calcula pisos | bloqueia se etapa 1 falhou |

Regras:

- Etapa só inicia quando a anterior terminar em `ok` ou `degradado`
- `falhou` na etapa 1 aborta a execução e me avisa. Sem partidas, nada mais faz sentido
- `degradado` significa parcial: registre `itens_ok` e `itens_erro` com o detalhe do que caiu
- A execução termina em `pronto` só se todas as etapas fecharam em `ok`
- Reexecutar uma etapa é idempotente e não recria o que já passou

## Palpites órfãos

Palpite pode chegar antes da partida existir no banco: fonte publica com 3 dias de antecedência, o job de partidas cobre 72h, e uma fonte publica para 4 dias à frente.

Palpite sem match vai para `picks_orfaos` com contador de tentativas, e o matching é reexecutado sobre a fila toda vez que a etapa `fixtures` traz partidas novas. Após 5 tentativas sem sucesso, vai para revisão manual.

Isso resolve o descompasso sem exigir que as fontes e a ESPN estejam sincronizadas no tempo.

## Aba 1: Saúde

Primeira tela ao abrir. Mostra o estado da execução do dia antes de qualquer outra coisa.

- Semáforo por etapa, com contagem de processados e de erro
- Fontes que falharam, com o erro e há quantos dias estão fora
- Quota do OddsPapi: consumido no mês, restante, projeção
- Palpites órfãos aguardando partida
- Partidas encerradas há mais de 12h sem liquidação
- Mensagens expiradas sem envio

**A aba de curadoria fica bloqueada enquanto a execução não chegar na etapa `slate`.** Se a execução terminou `degradado`, a curadoria abre com um aviso no topo dizendo exatamente o que está incompleto. Curar um slate sem saber que as odds de metade dos palpites falharam é o erro mais caro que esse console pode permitir.

## Aba 2: Curadoria

Lista o slate em rascunho, ordenado por kickoff. Cada item mostra:

- Partida, competição, kickoff no meu fuso, transmissão
- Fonte e tipster
- Mercado e seleção
- Odd citada pela fonte, odd de referência com origem, e o piso calculado
- Alerta quando a odd citada e a de referência divergem muito
- Alerta quando há conflito com outro palpite da mesma partida

Ações por item: remover, editar o piso, editar a odd de referência quando estiver faltando, reordenar. Ação global: adicionar palpite manual, aprovar o slate.

Regras de bloqueio da aprovação:

- Item sem odd de referência não pode ser aprovado
- Item com odd de referência abaixo de `ODD_MINIMA_ABSOLUTA` já vem excluído, com o motivo visível
- Conflito não resolvido bloqueia a aprovação
- Palpite de fonte em quarentena não aparece nesta aba, em hipótese alguma

Slate aprovado é imutável. Correção depois gera slate novo com referência ao anterior.

## Aba 3: Envio

Só abre depois do slate aprovado. Lista das mensagens com `status = pronta`, ordenadas por kickoff mais próximo. Cada card mostra:

- Nome do assinante e telefone
- Kickoff e quanto falta
- A mensagem renderizada, em monoespaçada, exatamente como vai sair
- Botão **Abrir no WhatsApp**: link `https://wa.me/{telefone_sem_mais}?text={mensagem_urlencoded}`, com `target="_blank"`
- Botão **Copiar texto**
- Botão **Marcar como enviada**
- Botão **Pular**, com campo de motivo

Detalhes que importam:

- Contador no topo: prontas, enviadas hoje, expirando nas próximas 2h
- Atalho: `Enter` marca como enviada e pula para o próximo
- Agrupe por assinante quando a mesma pessoa tem mais de uma mensagem, para eu mandar tudo numa conversa só
- Encoding: use `urllib.parse.quote`. Quebra de linha vira `%0A`. Teste com acento, emoji e texto longo
- Se o texto passar de 1500 caracteres, avise no card
- Painel lateral com assinaturas vencendo nos próximos 5 dias
- Botão "Regerar mensagem" para quando eu editar um template

## Janela de envio

Um envio por assinante por dia, cobrindo todos os jogos do slate.

- **Horário fixo: 9h, horário de Brasília.** A sessão de envio abre nesse horário
- **Ritmo de 30 segundos entre números.** O console conduz um card por vez, com contador regressivo, liberando o próximo depois do intervalo. Com 50 assinantes, a sessão dura cerca de 25 minutos
- O intervalo é ritmo da sessão manual, não agendamento. Eu continuo clicando cada envio
- **Ordem rotativa.** A sequência dos assinantes muda a cada dia, para a mesma pessoa não ficar sempre por último. Ordem determinística dentro do dia, para eu poder retomar a sessão se fechar o navegador

**Prazo mínimo: 2 horas antes do kickoff.** Como a sessão termina por volta das 9h25, isso exclui do slate qualquer partida com kickoff antes das 11h30. Corte na montagem do slate, com o motivo registrado, e mostre a contagem no console.

Configurações: `HORARIO_ENVIO` (09:00), `INTERVALO_ENVIO_SEGUNDOS` (30), `ANTECEDENCIA_MINIMA_HORAS` (2).

### Modo sessão no console

A aba de envio ganha um botão "iniciar sessão". Depois disso:

- Um card por vez, em foco, com o próximo bloqueado até o contador zerar
- Barra de progresso: enviados, restantes, tempo estimado
- Botão para pular o intervalo, caso eu queira acelerar, com aviso de que rajada de mensagens idênticas para muitos números é o padrão que mais chama atenção do WhatsApp
- Botão para pausar e retomar. A sessão sobrevive a fechar o navegador
- Ao final, resumo: enviados, pulados com motivo, e o que sobrou expirado

## Controle de assinatura

**Sem período de teste.** O valor mensal é baixo o suficiente para o próprio mês ser o teste.

**Sem renovação automática e sem cancelamento.** O pagamento é Pix registrado manualmente. A assinatura simplesmente vence na data e o acesso para. Quem quer continuar, paga de novo. Isso elimina a necessidade de fluxo de cancelamento, política de reembolso e cobrança recorrente.

O console mostra assinaturas vencendo nos próximos 5 dias, para eu cobrar antes de cortar.

## Teto operacional

**Máximo de 50 assinantes ativos nesta fase.** O envio é manual e o tempo é o limite real: 50 envios a 20 segundos cada são cerca de 17 minutos por dia, todo dia.

Implemente como validação dura: ao registrar assinatura que passaria de 50 ativos, o comando recusa e me avisa. Não é sugestão, é trava.

Quando o teto incomodar, a conversa é sobre canal, não sobre aumentar o número.

## Kill switch

Variável `QUEUE_ENABLED`. Quando `false`, a etapa `slate` não gera mensagens novas. O console continua mostrando o que já existe.

## Página pública de performance

O extrato é o argumento de venda e hoje só existe para quem já assina. Quem está avaliando não tem o que olhar.

Gere diariamente, a partir do extrato mestre, dois artefatos:

**1. Página HTML estática**, arquivo único, sem servidor, que eu posso hospedar em qualquer lugar ou mandar por link:

- Curva da banca simulada desde o início da operação
- ROI, volume, taxa de acerto e odd média, sempre juntos
- Contador de palpites não liquidados, ao lado do ROI
- Quebra por período: 7 dias, 30 dias, desde o início
- Data da última atualização, visível

**2. Resumo em texto**, formatado para eu colar direto no WhatsApp ao responder um interessado.

Regras de apresentação, obrigatórias no código e não configuráveis:

- A palavra "simulada" acompanha toda menção à banca
- Frase fixa explicando a metodologia: banca inicial, stake, e que o cálculo assume aposta feita ao **piso publicado**, não à odd real obtida pelo assinante
- Nenhum texto de projeção, previsão ou expectativa de retorno futuro
- Todo número acompanhado do período que cobre
- Aviso 18+ e jogo responsável no rodapé

Essa página usa o extrato mestre completo, nunca o de um assinante. Não exponha dado individual.

## Opt-in e opt-out

- Nenhum número entra na lista sem registro de opt-in com data, origem e evidência
- O opt-out chega como resposta no WhatsApp. Comando `python -m app.users optout --telefone +55...` para eu registrar em segundos
- Usuário com `opt_out_em` preenchido some do console na hora, inclusive das mensagens já geradas
- `python -m app.users export --user-id X` exporta tudo que o sistema guarda sobre a pessoa, para atender pedido sob LGPD

## Critérios de aceite

- Execução com etapa de odds falhando produz `degradado`, e a curadoria abre com aviso explícito
- Falha na etapa de partidas aborta a execução e não gera slate
- Palpite coletado antes da partida existir é vinculado automaticamente na próxima execução
- Link `wa.me` abre com o texto correto, incluindo acentos e quebras de linha
- Marcar como enviada é idempotente
- Opt-out remove a pessoa do console imediatamente
- Console utilizável com 50 mensagens na fila sem virar rolagem infinita

---

# Fase 6: Liquidação e banca simulada

O diferencial do produto. Sem histórico verificável, o sistema é só mais um canal de palpite. Com ele, cada usuário tem um extrato auditável do que teria acontecido se seguisse as indicações.

## 6a. Motor de liquidação

Um resolver por mercado, registrados num dicionário. Cada resolver recebe o `pick` e o `fixture` já encerrado e devolve resultado mais evidência.

```python
class MarketResolver(Protocol):
    market: str
    def resolve(self, pick: Pick, fixture: Fixture,
                stats: list[FixtureStats]) -> Resolution: ...
```

`Resolution` carrega o resultado, o fator de retorno e o JSON de evidência com exatamente os números usados na decisão. A evidência não é opcional: quando um usuário reclamar que um green virou red, você precisa mostrar o placar que o sistema usou.

### Resolvers da primeira entrega

| Mercado | Entrada | Complexidade |
|---|---|---|
| 1x2 | placar final | trivial |
| Dupla chance | placar final | trivial |
| Ambas marcam | placar final | trivial |
| Over/Under gols, linha .5 | placar final + linha | direto |
| Over/Under gols, linha inteira | placar final + linha | tem void na linha exata |
| Over/Under gols, linha .25 e .75 | placar final + linha | tem meio-green e meio-red |
| Handicap europeu | placar final + linha | direto |
| Handicap asiático | placar final + linha | tem meio-green e meio-red |
| Escanteios over/under | `fixture_stats` | depende de cobertura |
| Cartões, total da partida | `fixture_stats` | depende de cobertura |
| Cartões, condição por time | `fixture_stats` por time | resolver próprio, condição vale para os dois |

**Linhas quebradas valem para gols também, não só para handicap.** Foram observadas na fonte SDA entradas como "Mais 2.75 gols" e "Menos 2.25 gols". Uma linha 2.75 é metade em 2.5 e metade em 3.0: com 3 gols, metade ganha e metade devolve o stake. Tratar isso como over 2.5 comum superestima o resultado silenciosamente. Escreva teste para cada quarto de linha entre 0.25 e 4.75.

**Handicap asiático:** mesma lógica. Vitória por margem exata na linha inteira devolve o stake (`void`). Implemente com testes cobrindo cada caso, é onde erro passa despercebido.

**Void:** linha exata batida (over 2.0 com 2 gols), partida cancelada ou adiada, handicap zerado no empate. Stake volta, banca não muda.

**`nao_liquidavel`:** mercado sem resolver, ou resolver que precisa de estatística que a ESPN não trouxe para aquela partida. Nunca vira red. Fica fora do cálculo e aparece no relatório como pendência.

### Revisão manual

CLI `python -m app.settlement review` lista os `nao_liquidavel` e me deixa marcar o resultado na mão, gravando `revisado_por_humano = true`. Quando o volume disso passar de 15% dos palpites de uma fonte, quero um alerta.

### OddsPapi settlements: conferência, não substituto

O OddsPapi tem `/settlements?fixtureId=X`, que devolve o resultado de cada mercado da partida. Tentador usar como motor de liquidação e apagar toda a seção 6a. Não faça isso.

Dois motivos. O tier gratuito não comporta uma chamada de settlement por partida somada às chamadas de odds. E o histórico de resultados **é** o produto que eu vendo: terceirizar o cálculo dele para um fornecedor externo é fragilidade estrutural, não economia.

O uso correto é auxiliar:

- **Conferência amostral.** Uma vez por semana, escolha 5 palpites já liquidados pelos seus resolvers e compare com o settlement do OddsPapi. Divergência é bug seu, e quero ver no relatório
- **Saída para mercado sem resolver.** Antes de marcar `nao_liquidavel` e me mandar revisar na mão, consulte o settlement se houver quota sobrando
- Toda liquidação vinda dali grava `resolver = 'oddspapi'` na evidência, para eu saber o que é meu e o que é de terceiro

## 6b. Simulação de banca

Configuração por usuário: banca inicial (padrão 1000), stake em percentual (padrão a definir, ver pergunta abaixo) e modo de stake.

- **Fixo:** stake sempre calculado sobre a banca inicial. Uma sequência ruim não reduz a aposta. É a leitura mais honesta da performance dos palpites, porque isola o resultado do dimensionamento.
- **Proporcional:** stake calculado sobre a banca atual. Reflete melhor como a pessoa apostaria de verdade, e compõe ganhos e perdas.

Implemente os dois e deixe o padrão configurável. Se quiser opinar sobre qual usar como default, opine.

### Dois níveis de extrato

Como todo assinante recebe o mesmo slate, existe **um extrato mestre** com todos os palpites publicados desde o início da operação. É o track record do serviço, o número que vende a assinatura e o que você publica.

O extrato de cada usuário é um **recorte** do mestre, começando na data em que a assinatura dele passou a valer, com a banca dele resetada para o valor inicial nesse ponto. Quem assinou em março não carrega o resultado de janeiro.

```sql
master_ledger (id, pick_id, fixture_id, ordem, odd, resultado, fator_retorno, liquidado_em)
```

O extrato do usuário é calculado sob demanda a partir do `master_ledger`, filtrando por data e pelas exclusões de preferência dele. Não duplique o extrato mestre 200 vezes no banco.

### Entra no extrato

No mestre: todo palpite de slate aprovado que foi efetivamente enviado a pelo menos um assinante. Palpite removido na curadoria não entra. Palpite enviado depois do início do jogo não entra.

No extrato do usuário: os itens do mestre dentro do período de assinatura ativa dele, menos o que a preferência dele excluiu. Se o usuário ficou inadimplente e voltou, o período sem pagamento não gera entradas e a banca continua de onde parou.

A odd usada no cálculo é a **odd mínima publicada**, não a odd de referência e não a odd citada pelo tipster.

Essa é a decisão mais importante da fase. A odd mínima é a promessa que foi feita ao assinante: "não aposte abaixo de 1.65". Liquidar o extrato nesse piso significa que o histórico publicado é o pior caso. Quem conseguiu 1.72 teve resultado melhor que o número que você divulga.

**O extrato assume que a aposta foi feita, sempre.** Não há como saber se o assinante apostou, nem a que preço. Se a odd caiu abaixo do piso antes do kickoff e ele corretamente não apostou, o extrato ainda registra aquele palpite ao piso.

Isso é uma simplificação declarada, não um bug. Consequências:

- Não é preciso puxar odd de fechamento para verificar rompimento do piso. Economiza quota e uma camada inteira
- A divergência é simétrica: às vezes favorece, às vezes prejudica o número publicado. Não há viés sistemático numa direção
- **A metodologia precisa estar escrita em toda exibição do extrato**, semanal e pública: o cálculo assume aposta feita ao piso publicado

As outras duas odds continuam gravadas: `odd_citada` no palpite, `odd_referencia` no slate. Servem para auditoria e para o relatório de fontes, onde a diferença sistemática entre o que a fonte cita e o que o mercado brasileiro oferece diz muito sobre a qualidade dela.

### Cálculo

```
stake_valor = banca_base * stake_pct
retorno = stake_valor * fator_resultado
  green      -> odd
  meio_green -> (odd + 1) / 2
  void       -> 1
  meio_red   -> 0.5
  red        -> 0
banca_depois = banca_antes - stake_valor + retorno
```

Ordenação determinística por kickoff, com desempate pelo id do palpite. Reprocessar o extrato inteiro tem que dar exatamente o mesmo resultado, sempre. Escreva um teste que roda o recálculo duas vezes e compara.

## 6c. Métricas

Por usuário e por período (7 dias, 30 dias, desde o início):

- Banca atual e variação absoluta e percentual
- Total apostado, lucro, ROI (lucro / total apostado)
- Taxa de acerto, considerando meio-green como 0,5
- Odd média das entradas
- Drawdown máximo, e quanto tempo levou para recuperar
- Sequência atual de greens ou reds
- **Palpites não liquidados no período**, sempre exibido junto do ROI

Esse último item não é decoração. Se 20% dos palpites ficaram sem liquidar e você mostra o ROI dos 80% restantes, o número está viesado e você não sabe para que lado. Exiba os dois juntos ou não exiba nenhum.

## 6d. Performance por fonte

Mesmo motor, agrupamento diferente e escopo maior: **todos** os palpites liquidados, publicados ou não. Isso inclui fontes em quarentena, palpites cortados por conflito, palpites que eu removi na curadoria e palpites que o filtro de piso rejeitou.

Cada um deles tem odd de referência e odd mínima sombra, capturadas na coleta, então o ROI é calculável para todos. Essa é a razão de ter movido a captura da odd para lá.

Relatório `python -m app.reports sources --days 30`, com quebra por fonte, por tipster e por mercado:

- ROI, calculado sobre a odd mínima sombra
- Volume liquidado e volume `sem_odd`
- Taxa de acerto, considerando meio-green como 0,5
- Odd média
- Diferença média entre a odd citada pela fonte e a odd de referência
- Percentual de não liquidados

**Regra dura: nenhuma taxa de acerto é exibida sem o ROI ao lado.** Acerto isolado é a métrica que faz uma fonte de 89% com odds de 1.25 parecer boa quando o ROI é negativo. É exatamente o erro que este relatório existe para expor, e não pode reproduzi-lo.

**Comparabilidade.** Fonte publicada e fonte em quarentena são medidas sobre a mesma base: mesma fórmula de piso, mesma origem de odd, mesmo motor de liquidação. A única diferença é o destino do palpite. Sem isso, a decisão de tirar uma fonte da quarentena seria baseada em números que não conversam.

Fonte com ROI negativo por 60 dias e volume acima de 30 palpites deve aparecer com sugestão de desativação. Fonte em quarentena com ROI positivo consistente aparece com sugestão de promoção, sempre por mercado.

## 6e. Mensagem de resultado

Dois formatos novos de mensagem, entrando na mesma fila do console:

**Fechamento do palpite**, algumas horas após o jogo:

```
{{ time_casa }} {{ placar_casa }} x {{ placar_fora }} {{ time_fora }}

Palpite: {{ selecao }} @ {{ odd }}
{{ emoji_resultado }} {{ resultado_texto }}

Banca simulada: {{ banca_atual }} ({{ variacao_sinalizada }})
```

**Resumo semanal:**

```
Fala {{ primeiro_nome }}, fechamento da semana:

{{ total_palpites }} palpites, {{ greens }} greens e {{ reds }} reds
Banca simulada: {{ banca_inicial }} -> {{ banca_atual }}
ROI: {{ roi }}%
{% if nao_liquidados %}{{ nao_liquidados }} palpites sem resultado confirmado{% endif %}

{{ rodape_legal }}
```

Regras de apresentação, obrigatórias no código e não configuráveis:

- A palavra "simulada" acompanha toda menção à banca. Não é dinheiro, é registro histórico
- Nenhum texto de projeção, previsão ou expectativa de retorno futuro
- Resultado passado aparece sempre com o período que ele cobre
- O `rodape_legal` continua obrigatório

Isso não é excesso de cautela. A publicidade de apostas no Brasil tem restrição explícita sobre sugerir ganho garantido, e um número de banca crescendo numa mensagem sem contexto chega perto dessa linha. Manter o enquadramento de registro histórico resolve.

## Critérios de aceite

- Suíte de testes com pelo menos 40 casos de liquidação, cobrindo todas as linhas de handicap asiático e todos os casos de void
- Recalcular o extrato duas vezes produz resultado idêntico ao centavo
- Partida adiada gera void, nunca red
- Relatório por fonte roda em menos de 5 segundos com 5 mil palpites
- Nenhum ROI é exibido sem o contador de não liquidados ao lado

---

# Fase 7: Operação

- **Agendamento:** APScheduler dispara **uma execução diária às 6h, horário de Brasília**, que percorre as etapas em ordem. Três horas de folga antes da sessão de envio das 9h, suficientes para eu curar o slate com calma e para reexecutar uma etapa que tenha degradado. Jobs independentes fora dessa execução são apenas dois: coleta de resultados a cada 30min e liquidação a cada 30min, ambos posteriores ao jogo e sem dependência do slate
- **Mensagens de resultado:** fechamento dos palpites do dia gerado às 23h, resumo semanal na segunda-feira. Ambos entram na mesma fila do console e saem na sessão do dia seguinte
- **Health check:** a aba de saúde do console é a interface principal. O CLI `python -m app.health` devolve o mesmo em texto, para eu conferir sem abrir o navegador
- **Relatório diário:** envios do dia, pulos e motivos, opt-outs, liquidações e taxa de não liquidados
- **Página pública de performance:** regerada ao fim da liquidação diária
- **Backup:** dump diário do Postgres. O extrato de banca é o dado mais difícil de reconstruir, priorize a integridade dele

## Escala definida

O sistema atende no máximo 200 contatos e começa com muito menos. Não otimize para escala que não vai existir: nada de fila distribuída, worker pool ou cache em memória externa. Postgres e um processo só resolvem. Se em algum ponto você for propor infraestrutura acima disso, justifique com número.

---

# Perguntas que quero que você me faça antes de começar

Não presuma respostas. As decisões fechadas estão no topo do documento.

1. Quais ligas cobrir no lançamento e volume estimado de partidas por dia
2. Qual o conjunto de 4 a 6 torneios com cobertura confirmada de ESPN e OddsPapi, que define o escopo da quarentena
3. Qual o valor de `ODD_MINIMA_ABSOLUTA`. Abaixo de que cotação um palpite não vale ser recomendado
4. Banca inicial, valor do stake e modo, fixo ou proporcional
5. Quantos palpites por dia o slate deve ter no máximo
6. Como os assinantes entraram na lista, se já existe lista
7. Onde vai rodar: só na minha máquina ou tem servidor
8. O que acontece com o extrato de quem para de pagar e volta depois de dois meses

# Entregável da primeira resposta

Não escreva código ainda. Responda com:

1. Suas perguntas
2. O plano de fases com estimativa de esforço relativo
3. Os riscos técnicos que você enxerga que eu não listei
4. Sua avaliação sobre rodar a sonda da ESPN (Fase 1a) antes de qualquer outra coisa
5. Sua recomendação entre stake fixo e proporcional como padrão, com o argumento
6. Quais mercados vale implementar resolver na primeira entrega e quais deixar como `nao_liquidavel` até eu ver o volume real

# Sequência sugerida até o primeiro assinante

1. Sonda da ESPN e coleta de partidas funcionando
2. Coletor do SDA no modo recorrente, validado contra as armadilhas documentadas
3. Motor de liquidação com os resolvers principais e a suíte de testes
4. **Backfill de 90 dias do SDA**, rodado uma vez
5. Liquidação do backfill inteiro, gerando o primeiro relatório de ROI por fonte e por tipster
6. Com o relatório na mão: decidir `ODD_MINIMA_ABSOLUTA`, banca e stake
7. Console completo, slate curado, primeira sessão de envio

O passo 5 é o que separa esse produto de um canal de palpite qualquer. Não pule para o 6 antes de olhar o número.

**Ressalva sobre o backfill:** o histórico traz a odd citada pela fonte, mas não permite reconstruir a odd de referência nem o piso, porque não dá para consultar cotação de um jogo de dois meses atrás. O ROI do backfill sai calculado sobre a odd citada, que tende a ser ligeiramente otimista comparado ao que o extrato ao vivo vai produzir. Registre essa diferença no relatório e nunca publique o número do backfill como se fosse o extrato oficial.

# Riscos conhecidos e não resolvidos

Registrados para você não perder tempo os redescobrindo, e para eu não esquecer deles.

**Ponto único de falha humano.** Se eu não conseguir enviar num dia, ninguém recebe. Não há plano B, e com assinantes pagantes isso vira reclamação rápido. Se você tiver ideia de mitigação que não exija automatizar o WhatsApp, traga.

**Dependência de uma fonte só.** O SDA é a única fonte publicável com aderência ao público brasileiro. O limite de 50% de participação por fonte no slate vai apertar enquanto não houver uma segunda. Reporte quando o limite começar a cortar palpites por falta de alternativa.

**API interna da ESPN sem contrato.** Pode mudar sem aviso. É a razão de toda a validação com pydantic e do log de divergência de schema.

**Cobertura brasileira do OddsPapi é alegação do fornecedor.** Verificar com a chave gratuita antes de qualquer pagamento.

