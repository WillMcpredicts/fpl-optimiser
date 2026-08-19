"use client";

import { useMemo, useState } from "react";

import { BUDGET, SQUAD_SHAPE, TEAM_LIMIT, validateSquad } from "@/lib/squadRules";

type Option = {
  id: number;
  web_name: string;
  team: string;
  team_id: number;
  element_type: number;
  now_cost: number;
  points_3gw: number;
};

const SLOTS: { pos: number; label: string }[] = [];
for (const [pos, n] of Object.entries(SQUAD_SHAPE)) {
  const label = { 1: "GKP", 2: "DEF", 3: "MID", 4: "FWD" }[Number(pos)]!;
  for (let i = 0; i < n; i++) SLOTS.push({ pos: Number(pos), label });
}

export default function SquadForm({
  options,
  gw,
  initial,
}: {
  options: Option[];
  gw: number;
  initial: number[];
}) {
  const [picks, setPicks] = useState<number[]>(
    initial.length === 15 ? initial : SLOTS.map(() => 0),
  );
  const [bank, setBank] = useState("0.0");
  const [freeTransfers, setFreeTransfers] = useState("1");

  const byPos = useMemo(() => {
    const m = new Map<number, Option[]>();
    for (const o of options) m.set(o.element_type, [...(m.get(o.element_type) ?? []), o]);
    for (const list of m.values()) list.sort((a, b) => b.points_3gw - a.points_3gw);
    return m;
  }, [options]);

  const byId = useMemo(() => new Map(options.map((o) => [o.id, o])), [options]);
  const selected = picks.filter(Boolean).map((id) => byId.get(id)!).filter(Boolean);
  const spend = selected.reduce((a, p) => a + p.now_cost, 0);
  const bankTenths = Math.round(Number(bank || 0) * 10);
  const problems =
    selected.length === 15 ? validateSquad(selected, bankTenths) : [];
  const remaining = BUDGET - spend - bankTenths;

  return (
    <form method="post" action="/api/squad">
      <input type="hidden" name="gw" value={gw} />
      <div className="squad-grid">
        {SLOTS.map((slot, i) => (
          <label key={i} className="slot">
            <span className="pos">{slot.label}</span>
            <select
              name="player"
              value={picks[i] || ""}
              onChange={(e) => {
                const next = [...picks];
                next[i] = Number(e.target.value);
                setPicks(next);
              }}
              required
            >
              <option value="">— choose —</option>
              {(byPos.get(slot.pos) ?? []).map((o) => (
                <option key={o.id} value={o.id}>
                  {o.web_name} ({o.team}) £{(o.now_cost / 10).toFixed(1)} · {o.points_3gw.toFixed(1)}pts
                </option>
              ))}
            </select>
          </label>
        ))}
      </div>

      <div className="controls" style={{ marginTop: 14 }}>
        <label className="meta">
          Bank £m{" "}
          <input
            name="bank"
            type="number"
            step="0.1"
            min="0"
            value={bank}
            onChange={(e) => setBank(e.target.value)}
            style={{ width: 80 }}
          />
        </label>
        <label className="meta">
          Free transfers{" "}
          <input
            name="free_transfers"
            type="number"
            min="0"
            max="5"
            value={freeTransfers}
            onChange={(e) => setFreeTransfers(e.target.value)}
            style={{ width: 70 }}
          />
        </label>
        <label className="meta">
          Captain{" "}
          <select name="captain" defaultValue="">
            <option value="">— none —</option>
            {selected.map((p) => (
              <option key={p.id} value={p.id}>
                {p.web_name}
              </option>
            ))}
          </select>
        </label>
        <span className="meta">
          {selected.length}/15 · spent £{(spend / 10).toFixed(1)}m · unallocated £
          {(remaining / 10).toFixed(1)}m
        </span>
        <button type="submit" disabled={selected.length !== 15 || problems.length > 0}>
          Save squad
        </button>
      </div>

      {problems.length > 0 ? (
        <div className="banner" style={{ marginTop: 12 }}>
          <strong>Not a legal squad</strong>
          <ul>
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      ) : null}
      <p className="meta" style={{ marginTop: 8 }}>
        Max {TEAM_LIMIT} players per club, £100.0m total including the bank. Saving replaces
        the current squad; transfer suggestions are regenerated on the next planner run.
      </p>
    </form>
  );
}
