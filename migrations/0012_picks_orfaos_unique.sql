-- Fase 4: precisa de ON CONFLICT pra registrar motivo de exclusao
-- (sem_odd/descartado) sem duplicar linha a cada run de
-- scripts/resolve_odds.py - a coluna `tentativas` so faz sentido como
-- contador cumulativo se houver no maximo uma linha por pick.
alter table picks_orfaos add constraint picks_orfaos_pick_id_key unique (pick_id);
