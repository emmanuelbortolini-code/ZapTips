-- Correcao de design da 0013: o documento original diz explicitamente
-- que "correcao depois da aprovacao gera um slate novo com referencia ao
-- anterior" (slate aprovado e imutavel) - ou seja, PODE haver mais de um
-- daily_slates por `data` (uma cadeia de correcoes), o que a constraint
-- unique(data) da 0013 proibiria. Ainda nao existe codigo dependendo da
-- suposicao errada (motor de montagem foi escrito so depois deste
-- ajuste), entao corrige aqui em vez de carregar o erro adiante.
--
-- "Slate atual" de uma data vira consulta (o mais recente que nao foi
-- substituido), nao mais uma garantia de unicidade em nivel de schema.
alter table daily_slates drop constraint daily_slates_data_key;
alter table daily_slates add column criado_em timestamptz not null default now();
alter table daily_slates add column substitui_slate_id uuid references daily_slates(id);
