-- Record which squad an optimiser result was computed for.
--
-- Without this the Optimiser page had no way to know its stored results were
-- built from a squad that has since been replaced, so after any squad change it
-- kept recommending transfers against the old team until the next scheduled
-- run. transfer_suggestions already carried squad_id and correctly went blank;
-- this closes the same hole on the optimiser.

alter table optimal_squads
  add column if not exists squad_id bigint references my_squad(id) on delete cascade;

create index if not exists optimal_squads_squad_idx on optimal_squads (squad_id);
