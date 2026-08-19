import { promises as fs } from "node:fs";
import path from "node:path";

import { isConfigured, selectRows } from "./supabase";
import type { Dataset, PlayerRow, Position, Prediction } from "./types";

const SEASON = process.env.FPL_SEASON ?? "2026-27";
const SNAPSHOT = path.join(process.cwd(), "data", "snapshot.json");

type PlayerRecord = {
  id: number;
  web_name: string;
  team_id: number;
  element_type: Position;
  now_cost: number | null;
  status: string | null;
  news: string | null;
  selected_by_percent: number | null;
};

type TeamRecord = { id: number; short_name: string };

type PredictionRecord = Prediction & {
  season: string;
  player_id: number;
  model_version: string;
  computed_at: string;
};

function assemble(
  players: PlayerRecord[],
  teams: TeamRecord[],
  predictions: PredictionRecord[],
): { rows: PlayerRow[]; gameweeks: number[] } {
  const teamName = new Map(teams.map((t) => [t.id, t.short_name]));
  const byPlayer = new Map<number, Prediction[]>();
  for (const p of predictions) {
    const list = byPlayer.get(p.player_id) ?? [];
    list.push(p);
    byPlayer.set(p.player_id, list);
  }

  const gameweeks = [...new Set(predictions.map((p) => p.gw))].sort((a, b) => a - b);

  const rows: PlayerRow[] = [];
  for (const player of players) {
    const preds = byPlayer.get(player.id);
    if (!preds?.length) continue;

    const byGw: Record<number, Prediction> = {};
    let total = 0;
    for (const p of preds) {
      byGw[p.gw] = p;
      total += Number(p.final_score);
    }
    rows.push({
      player_id: player.id,
      web_name: player.web_name,
      team: teamName.get(player.team_id) ?? "?",
      position: player.element_type,
      price: (player.now_cost ?? 0) / 10,
      status: player.status,
      news: player.news,
      selected_by_percent: player.selected_by_percent,
      byGw,
      total,
      nextGw: gameweeks[0] ?? 0,
    });
  }

  rows.sort((a, b) => b.total - a.total);
  return { rows, gameweeks };
}

async function fromSnapshot(): Promise<Dataset | null> {
  try {
    const raw = await fs.readFile(SNAPSHOT, "utf8");
    const parsed = JSON.parse(raw) as {
      players: PlayerRecord[];
      teams: TeamRecord[];
      predictions: PredictionRecord[];
      generated_at: string;
      model_version: string;
      warnings?: string[];
    };
    const { rows, gameweeks } = assemble(parsed.players, parsed.teams, parsed.predictions);
    return {
      gameweeks,
      players: rows,
      source: "snapshot",
      generatedAt: parsed.generated_at,
      modelVersion: parsed.model_version,
      warnings: parsed.warnings ?? [],
    };
  } catch {
    return null;
  }
}

/**
 * Predictions for the projected horizon.
 *
 * Supabase is the real source. A local snapshot written by `ingest/dryrun.py`
 * is used as a fallback so the table is viewable before the database exists --
 * which is the whole of Phase 1's definition of done. The UI always says which
 * one it is reading, because a stale snapshot silently standing in for live
 * data is exactly the kind of thing this tool should never do.
 */
export async function loadDataset(): Promise<Dataset> {
  const warnings: string[] = [];

  if (isConfigured()) {
    try {
      const [players, teams, predictions] = await Promise.all([
        selectRows<PlayerRecord>(
          "players",
          `season=eq.${SEASON}&select=id,web_name,team_id,element_type,now_cost,status,news,selected_by_percent`,
        ),
        selectRows<TeamRecord>("teams", `season=eq.${SEASON}&select=id,short_name`),
        selectRows<PredictionRecord>("predicted_points", `season=eq.${SEASON}&select=*`),
      ]);

      if (predictions.length) {
        const { rows, gameweeks } = assemble(players, teams, predictions);
        const latest = predictions.reduce(
          (acc, p) => (p.computed_at > acc ? p.computed_at : acc),
          predictions[0].computed_at,
        );
        return {
          gameweeks,
          players: rows,
          source: "supabase",
          generatedAt: latest,
          modelVersion: predictions[0].model_version,
          warnings,
        };
      }
      warnings.push("Supabase is configured but holds no predictions yet -- run the ingestion.");
    } catch (err) {
      warnings.push(`Supabase read failed: ${(err as Error).message}`);
    }
  } else {
    warnings.push("Supabase is not configured (SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY).");
  }

  const snapshot = await fromSnapshot();
  if (snapshot) return { ...snapshot, warnings: [...warnings, ...snapshot.warnings] };

  return {
    gameweeks: [],
    players: [],
    source: "none",
    generatedAt: null,
    modelVersion: null,
    warnings: [
      ...warnings,
      "No local snapshot either. Run: .venv/bin/python ingest/dryrun.py 3 --snapshot",
    ],
  };
}
