import { NextResponse } from "next/server";

import { MAX_FREE_TRANSFERS, sellingPrice, validateSquad } from "@/lib/squadRules";

const SEASON = process.env.FPL_SEASON ?? "2026-27";
const URL_BASE = (process.env.SUPABASE_URL ?? "").replace(/\/$/, "");
const KEY = process.env.SUPABASE_SERVICE_ROLE_KEY ?? "";

function headers(prefer: string) {
  return {
    apikey: KEY,
    Authorization: `Bearer ${KEY}`,
    "Content-Type": "application/json",
    Prefer: prefer,
  };
}

export async function POST(request: Request) {
  if (!URL_BASE || !KEY) {
    return NextResponse.redirect(new URL("/squad?error=Supabase+is+not+configured", request.url), {
      status: 303,
    });
  }

  const form = await request.formData();
  const ids = form
    .getAll("player")
    .map((v) => Number(v))
    .filter((n) => Number.isFinite(n) && n > 0);
  const bank = Math.round(Number(form.get("bank") ?? 0) * 10);
  const freeTransfers = Math.min(Number(form.get("free_transfers") ?? 1), MAX_FREE_TRANSFERS);
  const gw = Number(form.get("gw") ?? 1);
  const captain = Number(form.get("captain") ?? 0) || null;

  const fail = (msg: string) =>
    NextResponse.redirect(new URL(`/squad?error=${encodeURIComponent(msg)}`, request.url), {
      status: 303,
    });

  if (ids.length !== 15) return fail(`Select all 15 players (got ${ids.length}).`);
  if (!Number.isFinite(bank) || bank < 0) return fail("Bank must be zero or more.");

  const res = await fetch(
    `${URL_BASE}/rest/v1/players?season=eq.${SEASON}&select=id,element_type,team_id,now_cost&id=in.(${ids.join(",")})`,
    { headers: headers("return=representation"), cache: "no-store" },
  );
  if (!res.ok) return fail(`Could not read players: ${await res.text()}`);
  const players = (await res.json()) as {
    id: number;
    element_type: number;
    team_id: number;
    now_cost: number;
  }[];
  if (players.length !== 15) return fail("Some selected players were not found.");

  const problems = validateSquad(players, bank);
  if (problems.length) return fail(problems.join("; "));

  // Only one squad is current; the rest become history.
  await fetch(`${URL_BASE}/rest/v1/my_squad?season=eq.${SEASON}&is_current=is.true`, {
    method: "PATCH",
    headers: headers("return=minimal"),
    body: JSON.stringify({ is_current: false }),
  });

  const squadValue = players.reduce((a, p) => a + p.now_cost, 0);
  const created = await fetch(`${URL_BASE}/rest/v1/my_squad`, {
    method: "POST",
    headers: headers("return=representation"),
    body: JSON.stringify({
      season: SEASON,
      gw,
      source: "manual",
      bank,
      squad_value: squadValue,
      free_transfers: freeTransfers,
      is_current: true,
    }),
  });
  if (!created.ok) return fail(`Could not save squad: ${await created.text()}`);
  const squadId = (await created.json())[0].id as number;

  const byId = new Map(players.map((p) => [p.id, p]));
  const picks = ids.map((id, i) => {
    const p = byId.get(id)!;
    return {
      squad_id: squadId,
      player_id: id,
      position: i + 1,
      is_captain: id === captain,
      is_vice_captain: false,
      // No public endpoint exposes what I paid, so selling value falls back to
      // current price. Exact if bought at today's price, conservative otherwise.
      purchase_price: p.now_cost,
      selling_price: sellingPrice(p.now_cost, p.now_cost),
    };
  });
  const savedPicks = await fetch(`${URL_BASE}/rest/v1/my_squad_picks`, {
    method: "POST",
    headers: headers("return=minimal"),
    body: JSON.stringify(picks),
  });
  if (!savedPicks.ok) return fail(`Could not save picks: ${await savedPicks.text()}`);

  return NextResponse.redirect(new URL("/squad?saved=1", request.url), { status: 303 });
}
