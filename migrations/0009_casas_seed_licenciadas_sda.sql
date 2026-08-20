-- Fase 2, Fonte 2: o SDA cita Superbet, Betano e bet365 (ja cadastradas
-- na Fase 1g via scripts/collect_odds.py, mesmo nome) mais Novibet,
-- BetBoom e VBET (sem cobertura no OddsPapi - ver CLAUDE.md Fase 1b).
-- Todas licenciadas no Brasil, numero SPA/MF publicado (documento
-- original, secao "Casas citadas").
insert into casas (nome, licenciada_br, ativa)
values
    ('Bet365', true, true),
    ('Betano', true, true),
    ('Superbet', true, true),
    ('Novibet', true, true),
    ('BetBoom', true, true),
    ('VBET', true, true)
on conflict (nome) do update set licenciada_br = true, ativa = true;
