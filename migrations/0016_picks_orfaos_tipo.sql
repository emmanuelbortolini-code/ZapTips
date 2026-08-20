-- Fase 5a: picks_orfaos ate aqui so guardava picks excluidos da curadoria
-- (sem_odd/conflito), escritos por resolve_odds.py e build_slate.py. A
-- Fase 5a introduz um segundo uso da mesma tabela: pick que chegou antes
-- da fixture existir, com contador de tentativas de rematching ate 5
-- (ver CLAUDE.md, Fase 5a). Sem separar por tipo, os dois contadores
-- colidiriam na mesma linha (unique em pick_id, migration 0012).
alter table picks_orfaos add column tipo text;
update picks_orfaos set tipo = 'excluido' where tipo is null;
alter table picks_orfaos alter column tipo set not null;
alter table picks_orfaos add constraint picks_orfaos_tipo_check
    check (tipo in ('sem_fixture', 'excluido'));
alter table picks_orfaos drop constraint picks_orfaos_pick_id_key;
alter table picks_orfaos add constraint picks_orfaos_pick_id_tipo_key unique (pick_id, tipo);
