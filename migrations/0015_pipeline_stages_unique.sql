-- Fase 5a: o orquestrador de pipeline precisa de ON CONFLICT pra fazer
-- upsert de uma etapa (marcar 'rodando', depois fechar com resultado)
-- sem duplicar linha quando o run e retomado no mesmo dia.
alter table pipeline_stages add constraint pipeline_stages_run_id_etapa_key unique (run_id, etapa);
