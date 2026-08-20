-- Fase 3: rastreia se um raw_pick ja passou pela extracao estruturada
-- (LLM), independente de ter gerado 0, 1 ou varios palpites. Sem essa
-- coluna nao da pra distinguir "post sem nenhum palpite real" de "ainda
-- nao processado" so olhando a ausencia de linhas em picks.
alter table raw_picks add column if not exists extraido_em timestamptz;
