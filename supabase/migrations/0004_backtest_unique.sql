-- One backtest verdict per (season, stat, confidence tier), so a re-run updates
-- the previous result rather than appending a second, contradictory one.
--
-- backtest_results has a surrogate `id`, which is not a usable conflict target:
-- upserting on it would treat every fresh row as new. This is the real key.

alter table backtest_results
  drop constraint if exists backtest_results_unique;

alter table backtest_results
  add constraint backtest_results_unique unique (season, stat_type, confidence);
