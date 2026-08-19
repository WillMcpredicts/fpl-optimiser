/**
 * FPL squad rules, mirrored from ingest/squad.py and ingest/planner.py.
 *
 * Duplicated deliberately and kept small: the browser form has to validate
 * before writing, and the Python pipeline has to validate what it reads. If
 * these ever disagree, the Python is canonical -- it is what actually scores.
 */
export const SQUAD_SHAPE: Record<number, number> = { 1: 2, 2: 5, 3: 5, 4: 3 };
export const TEAM_LIMIT = 3;
export const BUDGET = 1000; // tenths of a million
export const MAX_FREE_TRANSFERS = 5;

/** FPL returns half of any price rise, rounded down to 0.1m. */
export function sellingPrice(purchase: number | null, nowCost: number): number {
  if (purchase === null || nowCost <= purchase) return nowCost;
  return purchase + Math.floor((nowCost - purchase) / 2);
}

export function validateSquad(
  players: { id: number; element_type: number; team_id: number; now_cost: number }[],
  bank: number,
): string[] {
  const problems: string[] = [];
  const ids = players.map((p) => p.id);
  if (new Set(ids).size !== ids.length) problems.push("the same player appears more than once");

  const names: Record<number, string> = { 1: "goalkeepers", 2: "defenders", 3: "midfielders", 4: "forwards" };
  const byPos: Record<number, number> = {};
  const byTeam: Record<number, number> = {};
  let total = 0;
  for (const p of players) {
    byPos[p.element_type] = (byPos[p.element_type] ?? 0) + 1;
    byTeam[p.team_id] = (byTeam[p.team_id] ?? 0) + 1;
    total += p.now_cost;
  }
  for (const [pos, want] of Object.entries(SQUAD_SHAPE)) {
    const got = byPos[Number(pos)] ?? 0;
    if (got !== want) problems.push(`${got} ${names[Number(pos)]}, expected ${want}`);
  }
  const over = Object.values(byTeam).filter((n) => n > TEAM_LIMIT).length;
  if (over) problems.push(`more than ${TEAM_LIMIT} players from one club (${over} club(s) over)`);
  if (total + bank > BUDGET) {
    problems.push(
      `squad ${(total / 10).toFixed(1)} plus bank ${(bank / 10).toFixed(1)} exceeds the 100.0 budget`,
    );
  }
  return problems;
}
