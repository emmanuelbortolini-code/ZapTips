-- Fase 3: os campos que a extracao devolve (time_casa/time_fora/
-- competicao/data_referencia/unidades) precisam de onde morar em picks -
-- sem essas colunas o dado seria descartado no momento em que
-- raw_picks.extraido_em e marcado, sem como recuperar depois sem
-- reprocessar (sem garantia de saida identica do modelo). Fase 4
-- (matching contra fixtures, via picks.fixture_id) depende diretamente
-- de time_casa/time_fora/data_referencia existirem aqui.
--
-- data_referencia fica como texto livre (nao date/timestamptz): o
-- tipster referencia data de forma solta ("hoje", "amanha", "sabado"),
-- normalizar isso pra uma data real e trabalho de matching (Fase 4), nao
-- de extracao.
alter table picks add column if not exists time_casa text;
alter table picks add column if not exists time_fora text;
alter table picks add column if not exists competicao text;
alter table picks add column if not exists data_referencia text;
alter table picks add column if not exists unidades numeric(6, 2);
