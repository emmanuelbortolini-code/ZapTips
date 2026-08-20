-- Fase 1c: seed de team_aliases a partir do endpoint /teams da ESPN precisa
-- ser idempotente (rodar 2x nao duplica alias, mesmo criterio de aceite da
-- Fase 1 ja usado para fixtures). Sem essa constraint, o upsert do script
-- de seed nao tem o que usar em ON CONFLICT.
alter table team_aliases
    add constraint team_aliases_team_alias_normalizado_key unique (team_id, alias_normalizado);
