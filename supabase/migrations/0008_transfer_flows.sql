-- Weekly transfer flows, as a crowd signal.
--
-- The market sees things the model cannot: press conferences, expected
-- line-ups, the eye test. Net transfers in the days before a deadline are that
-- knowledge made visible, and worth testing as an input.

alter table player_gameweeks
  add column if not exists transfers_in      int,
  add column if not exists transfers_out     int,
  add column if not exists transfers_balance int,
  add column if not exists selected          int;
