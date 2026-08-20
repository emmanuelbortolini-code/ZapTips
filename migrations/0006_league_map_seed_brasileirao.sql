-- Fase 1g: bra.1 (Serie A, tournamentId 325) e bra.2 (Serie B,
-- tournamentId 390) sao os 2 unicos torneios com cobertura ESPN+OddsPapi
-- confirmada com dado real ate agora (Fase 1b, ver CLAUDE.md). Os outros
-- codigos de liga do documento original (eng.1, esp.1, uefa.champions,
-- etc.) ainda nao passaram pela mesma verificacao - o PM preenche o
-- resto na mao depois de confirmar tournamentId e cobertura real, como o
-- documento original pede.
insert into league_map (espn_league_code, oddspapi_tournament_id, nome, ativa)
values
    ('bra.1', '325', 'Brasileirao Serie A', true),
    ('bra.2', '390', 'Brasileirao Serie B', true)
on conflict (espn_league_code) do nothing;
