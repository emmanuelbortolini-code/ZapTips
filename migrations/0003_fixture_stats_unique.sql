-- Fase 1f: job de coleta de resultados precisa upsert idempotente em
-- fixture_stats (um time pode ter suas estatisticas atualizadas se o job
-- rodar de novo antes do proximo ciclo). Sem essa constraint, ON CONFLICT
-- nao tem o que usar.
alter table fixture_stats
    add constraint fixture_stats_fixture_time_key unique (fixture_id, time_id);
