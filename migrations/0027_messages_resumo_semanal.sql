-- Fase 6e (resumo semanal): ultimo pedaco da fase, adiado desde a
-- mensagem de fechamento (migrations/0026_messages_tipo.sql) porque
-- exigia isto - resumo semanal e' um agregado da semana inteira
-- (segunda a domingo, app.pipeline.semana_operacional_anterior), sem
-- fixture nenhuma associada. Diferente de 'palpite'/'fechamento', que
-- sempre apontam pra uma partida.
alter table messages alter column fixture_id drop not null;

alter table messages drop constraint messages_tipo_check;
alter table messages add constraint messages_tipo_check
    check (tipo in ('palpite', 'fechamento', 'resumo_semanal'));
