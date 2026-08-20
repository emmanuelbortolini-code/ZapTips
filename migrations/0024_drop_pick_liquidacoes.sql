-- Fase 6a: revertendo migrations/0023_pick_liquidacoes.sql. Achado do
-- code-reviewer: o projeto ja tem uma tabela pra exatamente esse
-- proposito desde a Fase 0, `pick_results` (migrations/0001_init.sql),
-- ja usada pela metrica "encerradas_sem_liquidacao" do console
-- (app/console/queries.py, tests/test_console_queries.py). Criar
-- `pick_liquidacoes` como tabela paralela quebraria essa metrica
-- silenciosamente - o dashboard nunca zeraria o backlog, porque nada
-- mais escreveria em pick_results. A liquidacao da Fase 6a passa a
-- escrever em pick_results diretamente - ver
-- app/settlement/persistencia.py. Mesmo tratamento ja dado ao erro de
-- `unique(data)` em daily_slates (migration 0013 -> 0014): reverter com
-- uma migration nova em vez de editar a ja aplicada.
drop index if exists idx_pick_liquidacoes_fixture;
drop index if exists uniq_pick_liquidacoes_pick_id;
drop table if exists pick_liquidacoes;
