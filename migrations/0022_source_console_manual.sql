-- Fase 5d (pendencia D3 da Fase 5c): palpite manual digitado direto no
-- console precisa de uma fonte que NAO nasca em quarentena - senao ele
-- desaparece da propria aba que o criou (carregar_itens_slate/
-- buscar_picks_candidatos filtram sources.quarentena is not true desde
-- o CRITICAL corrigido na Fase 5c). app.sources.upsert_source forca
-- quarentena=true de proposito (regra geral: toda fonte nasce
-- quarentenada, sair e decisao do PM medida por performance) - esta e
-- a UNICA excecao, porque conteudo digitado pelo proprio operador na
-- curadoria ja E a curadoria, nao precisa da mesma trava de confianca
-- que uma fonte automatica externa precisa.
insert into sources (nome, tipo, ativo, quarentena)
values ('console_manual', 'manual', true, false)
on conflict (nome) do nothing;
