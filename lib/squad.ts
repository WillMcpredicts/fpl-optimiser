import { isConfigured, selectRows } from "./supabase";
import type { Position } from "./types";

const SEASON = process.env.FPL_SEASON ?? "2026-27";

export type SquadPlayer = {
  player_id: number;
  web_name: string;
  team: string;
  position: Position;
  selling_price: number;
  purchase_price: number;
  points_next: number;
  points_3gw: number;
  status: string | null;
  news: string | null;
  selected_by_percent: number | null;
  is_captain: boolean;
  is_vice_captain: boolean;
  inBestXi: boolean;
  bracketPercentile: number | null;
};

export type PlanStep = {
  step: number;
  marginal_hit: number;
  net_after_hit: number;
  cumulative_net: number;
  bank_after: number;
  recommended_depth: number;
  in_recommended_plan: boolean;
  gross: number;
};

export type Suggestion = {
  id: number;
  rank: number;
  player_out: number;
  player_in: number;
  out_cost: number;
  in_cost: number;
  cash_delta: number;
  hit_cost: number;
  gross_gain_3gw: number;
  net_gain_3gw: number;
  reasoning: {
    out: Record<string, unknown> & { name: string; team: string; price: number; points_3gw: number; in_best_xi: boolean; news: string | null; price_bracket_percentile: number | null };
    in: Record<string, unknown> & { name: string; team: string; price: number; points_3gw: number; ownership: number | null; price_bracket_percentile: number | null };
    per_gameweek: Record<string, { out: number; in: number }>;
    economy: { free_transfers_available: number; hit_if_taken_alone: number };
    plan: PlanStep | null;
  };
};

export type SquadData = {
  configured: boolean;
  hasSquad: boolean;
  error: string | null;
  gw: number;
  gameweeks: number[];
  bank: number;
  squadValue: number;
  freeTransfers: number;
  source: string;
  players: SquadPlayer[];
  suggestions: Suggestion[];
};

const FORMATIONS: [number, number, number][] = [];
for (let d = 3; d <= 5; d++)
  for (let m = 2; m <= 5; m++)
    for (let f = 1; f <= 3; f++) if (1 + d + m + f === 11) FORMATIONS.push([d, m, f]);

/** Highest-scoring legal XI. Mirrors ingest/planner.py so the UI agrees with it. */
export function bestXi(players: SquadPlayer[]): Set<number> {
  const byPos = new Map<number, SquadPlayer[]>();
  for (const p of players) {
    byPos.set(p.position, [...(byPos.get(p.position) ?? []), p]);
  }
  for (const list of byPos.values()) list.sort((a, b) => b.points_3gw - a.points_3gw);

  let bestTotal = -1;
  let best: Set<number> = new Set();
  for (const [d, m, f] of FORMATIONS) {
    const counts: Record<number, number> = { 1: 1, 2: d, 3: m, 4: f };
    if (Object.entries(counts).some(([pos, n]) => (byPos.get(Number(pos))?.length ?? 0) < n)) {
      continue;
    }
    let total = 0;
    const ids = new Set<number>();
    for (const [pos, n] of Object.entries(counts)) {
      for (const p of (byPos.get(Number(pos)) ?? []).slice(0, n)) {
        total += p.points_3gw;
        ids.add(p.player_id);
      }
    }
    if (total > bestTotal) {
      bestTotal = total;
      best = ids;
    }
  }
  return best;
}

export async function loadSquad(): Promise<SquadData> {
  const empty: SquadData = {
    configured: isConfigured(),
    hasSquad: false,
    error: null,
    gw: 0,
    gameweeks: [],
    bank: 0,
    squadValue: 0,
    freeTransfers: 1,
    source: "",
    players: [],
    suggestions: [],
  };
  if (!isConfigured()) return { ...empty, error: "Supabase is not configured." };

  try {
    const squads = await selectRows<{
      id: number;
      gw: number;
      bank: number;
      squad_value: number | null;
      free_transfers: number;
      source: string;
    }>("my_squad", `season=eq.${SEASON}&is_current=is.true&select=*`);
    if (!squads.length) return empty;
    const squad = squads[0];

    const [picks, players, teams, predictions, suggestions] = await Promise.all([
      selectRows<{
        player_id: number;
        selling_price: number;
        purchase_price: number;
        is_captain: boolean;
        is_vice_captain: boolean;
      }>("my_squad_picks", `squad_id=eq.${squad.id}&select=*`),
      selectRows<{
        id: number;
        web_name: string;
        team_id: number;
        element_type: Position;
        now_cost: number;
        status: string | null;
        news: string | null;
        selected_by_percent: number | null;
      }>("players", `season=eq.${SEASON}&select=*`),
      selectRows<{ id: number; short_name: string }>("teams", `season=eq.${SEASON}&select=id,short_name`),
      selectRows<{ player_id: number; gw: number; final_score: number }>(
        "predicted_points",
        `season=eq.${SEASON}&select=player_id,gw,final_score`,
      ),
      selectRows<Suggestion>(
        "transfer_suggestions",
        `season=eq.${SEASON}&squad_id=eq.${squad.id}&select=*&order=rank`,
      ),
    ]);

    const gameweeks = [...new Set(predictions.map((p) => p.gw))].sort((a, b) => a - b).slice(0, 3);
    const pts = new Map<number, Map<number, number>>();
    for (const p of predictions) {
      if (!gameweeks.includes(p.gw)) continue;
      const m = pts.get(p.player_id) ?? new Map();
      m.set(p.gw, Number(p.final_score));
      pts.set(p.player_id, m);
    }
    const total3 = (id: number) => [...(pts.get(id)?.values() ?? [])].reduce((a, b) => a + b, 0);
    const teamName = new Map(teams.map((t) => [t.id, t.short_name]));
    const playerById = new Map(players.map((p) => [p.id, p]));

    // Percentile against same-position players within 0.5m, matching the planner.
    const universe = players.map((p) => ({
      id: p.id,
      element_type: p.element_type,
      now_cost: p.now_cost ?? 0,
      points_3gw: total3(p.id),
    }));
    const percentile = (id: number) => {
      const me = universe.find((u) => u.id === id);
      if (!me) return null;
      const peers = universe.filter(
        (u) => u.element_type === me.element_type && Math.abs(u.now_cost - me.now_cost) <= 5 && u.id !== id,
      );
      if (peers.length < 4) return null;
      return peers.filter((u) => u.points_3gw < me.points_3gw).length / peers.length;
    };

    const squadPlayers: SquadPlayer[] = [];
    for (const pick of picks) {
      const p = playerById.get(pick.player_id);
      if (!p) continue;
      squadPlayers.push({
        player_id: p.id,
        web_name: p.web_name,
        team: teamName.get(p.team_id) ?? "?",
        position: p.element_type,
        selling_price: pick.selling_price,
        purchase_price: pick.purchase_price,
        points_next: pts.get(p.id)?.get(gameweeks[0]) ?? 0,
        points_3gw: total3(p.id),
        status: p.status,
        news: p.news,
        selected_by_percent: p.selected_by_percent,
        is_captain: pick.is_captain,
        is_vice_captain: pick.is_vice_captain,
        inBestXi: false,
        bracketPercentile: percentile(p.id),
      });
    }
    const xi = bestXi(squadPlayers);
    for (const p of squadPlayers) p.inBestXi = xi.has(p.player_id);

    return {
      ...empty,
      hasSquad: true,
      gw: squad.gw,
      gameweeks,
      bank: squad.bank,
      squadValue: squad.squad_value ?? squadPlayers.reduce((a, p) => a + p.selling_price, 0),
      freeTransfers: squad.free_transfers,
      source: squad.source,
      players: squadPlayers,
      suggestions,
    };
  } catch (err) {
    return { ...empty, error: (err as Error).message };
  }
}
