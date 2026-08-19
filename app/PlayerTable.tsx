"use client";

import { Fragment, useMemo, useState } from "react";

import { POSITION_NAMES, type Dataset, type PlayerRow, type Prediction } from "@/lib/types";

function num(v: number, dp = 2) {
  return v.toFixed(dp);
}

function Delta({ value }: { value: number }) {
  if (Math.abs(value) < 0.005) return <span className="meta">0.00</span>;
  return (
    <span className={`delta ${value > 0 ? "pos-val" : "neg-val"}`}>
      {value > 0 ? "+" : ""}
      {num(value)}
    </span>
  );
}

/**
 * Principle 8: every figure shows its working. The breakdown is not a nicety --
 * a single opaque number is exactly what this tool is meant to avoid.
 */
function Breakdown({ p }: { p: Prediction }) {
  const c = p.confidence_breakdown;
  const comps = Object.entries(c.components ?? {}).filter(([, v]) => Math.abs(v) > 0.001);
  return (
    <div className="breakdown">
      <div className="grid">
        <div>
          <h4>Score</h4>
          <div className="row"><span>Base (average opponent)</span><span>{num(p.base_score)}</span></div>
          <div className="row"><span>Fixture adjustment</span><span><Delta value={Number(p.fixture_adjustment)} /></span></div>
          <div className="row"><span>Trend adjustment</span><span><Delta value={Number(p.trend_adjustment)} /></span></div>
          <div className="row"><span>BPS adjustment</span><span><Delta value={Number(p.bps_adjustment)} /></span></div>
          <div className="row"><span><strong>Final</strong></span><span><strong>{num(p.final_score)}</strong></span></div>
        </div>

        <div>
          <h4>Minutes</h4>
          <div className="row"><span>Expected minutes</span><span>{num(p.expected_minutes, 0)}</span></div>
          <div className="row"><span>P(60+ minutes)</span><span>{num(p.minutes_probability)}</span></div>
          <div className="row"><span>Availability</span><span>{num(c.availability)}</span></div>
          <div className="row"><span>Reason</span><span>{c.availability_reason}</span></div>
          <div className="row"><span>Depth rank (price)</span><span>{String((c as never as Record<string, unknown>).depth_rank ?? "-")}</span></div>
        </div>

        <div>
          <h4>Points sources</h4>
          {comps.length === 0 ? <div className="meta">none</div> : null}
          {comps.map(([k, v]) => (
            <div className="row" key={k}>
              <span>{k.replace(/_/g, " ")}</span>
              <span>{num(v)}</span>
            </div>
          ))}
        </div>

        <div>
          <h4>Underlying rates</h4>
          {Object.entries(c.rates ?? {}).map(([k, v]) => (
            <div className="row" key={k}>
              <span>{k}</span>
              <span>{num(Number(v), k === "avg_minutes" ? 0 : 3)}</span>
            </div>
          ))}
          <div className="row"><span>Evidence (90s)</span><span>{c.evidence_90s}</span></div>
          <div className="row"><span>This season (90s)</span><span>{c.current_season_90s}</span></div>
        </div>

        <div>
          <h4>Fixtures</h4>
          {c.fixtures?.length ? (
            c.fixtures.map((f) => (
              <div className="row" key={f.fixture_id}>
                <span>
                  {f.opponent ?? "?"} ({f.is_home ? "H" : "A"})
                </span>
                <span>
                  {num(f.points)} · CS {num(f.clean_sheet_probability)}
                </span>
              </div>
            ))
          ) : (
            <div className="meta">No fixture this gameweek (blank)</div>
          )}
        </div>
      </div>

      <div className="equation">
        {num(p.base_score)} base {Number(p.fixture_adjustment) >= 0 ? "+" : "−"}{" "}
        {num(Math.abs(Number(p.fixture_adjustment)))} fixture{" "}
        {Number(p.trend_adjustment) >= 0 ? "+" : "−"} {num(Math.abs(Number(p.trend_adjustment)))} trend
        {" = "}
        {num(p.final_score)} predicted points
      </div>
      {c.trend_engine ? <div className="meta" style={{ marginTop: 6 }}>Trend engine: {c.trend_engine}</div> : null}
    </div>
  );
}

type SortKey = "total" | "next" | "price" | "value" | "minutes" | "form" | "owned" | "differential";
type ViewKey = "projection" | "sources" | "value";

const SOURCE_COLUMNS: [string, string][] = [
  ["goals", "Goals"],
  ["assists", "Assists"],
  ["clean_sheet", "Clean sheets"],
  ["defcon", "DefCon"],
  ["bonus", "Bonus"],
  ["saves", "Saves"],
  ["appearance", "Appearance"],
  ["conceded", "Conceded"],
  ["penalties", "Pen duty"],
];

export default function PlayerTable({ data }: { data: Dataset }) {
  const [query, setQuery] = useState("");
  const [position, setPosition] = useState("ALL");
  const [maxPrice, setMaxPrice] = useState("");
  const [sort, setSort] = useState<SortKey>("total");
  const [view, setView] = useState<ViewKey>("projection");
  const [open, setOpen] = useState<number | null>(null);

  const gws = data.gameweeks;
  const firstGw = gws[0];

  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const cap = maxPrice ? Number(maxPrice) : Infinity;

    const filtered = data.players.filter((p) => {
      if (position !== "ALL" && POSITION_NAMES[p.position] !== position) return false;
      if (p.price > cap) return false;
      if (!q) return true;
      return (
        p.web_name.toLowerCase().includes(q) || p.team.toLowerCase().includes(q)
      );
    });

    const score = (p: PlayerRow) => {
      switch (sort) {
        case "next":
          return p.byGw[firstGw]?.final_score ?? 0;
        case "price":
          return p.price;
        case "value":
          return p.price > 0 ? p.total / p.price : 0;
        case "minutes":
          return p.byGw[firstGw]?.expected_minutes ?? 0;
        case "form":
          return Number(p.form ?? 0);
        case "owned":
          return Number(p.selected_by_percent ?? 0);
        case "differential":
          // High projection, low ownership: how you gain rank rather than
          // track it. Ownership is floored so a 0% player is not infinite.
          return p.total / Math.max(0.5, Number(p.selected_by_percent ?? 0));
        default:
          return p.total;
      }
    };
    return [...filtered].sort((a, b) => score(b) - score(a));
  }, [data.players, query, position, maxPrice, sort, firstGw]);

  return (
    <>
      <div className="controls">
        <input
          placeholder="Search player or team"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
        />
        <select value={position} onChange={(e) => setPosition(e.target.value)}>
          <option value="ALL">All positions</option>
          <option value="GKP">Goalkeepers</option>
          <option value="DEF">Defenders</option>
          <option value="MID">Midfielders</option>
          <option value="FWD">Forwards</option>
        </select>
        <input
          type="number"
          step="0.1"
          placeholder="Max £"
          value={maxPrice}
          onChange={(e) => setMaxPrice(e.target.value)}
          style={{ width: 90 }}
        />
        <select value={view} onChange={(e) => setView(e.target.value as ViewKey)}>
          <option value="projection">View: projection</option>
          <option value="sources">View: where the points come from</option>
          <option value="value">View: value, price &amp; ownership</option>
        </select>
        <select value={sort} onChange={(e) => setSort(e.target.value as SortKey)}>
          <option value="total">Sort: total over {gws.length} GWs</option>
          <option value="next">Sort: next GW</option>
          <option value="value">Sort: points per £m</option>
          <option value="differential">Sort: differential (points vs ownership)</option>
          <option value="minutes">Sort: expected minutes</option>
          <option value="form">Sort: form</option>
          <option value="owned">Sort: ownership</option>
          <option value="price">Sort: price</option>
        </select>
        <span className="meta">{rows.length} players</span>
      </div>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th className="left">Player</th>
              <th className="left">Team</th>
              <th className="left">Pos</th>
              <th>£</th>
              {view === "projection" ? (
                <>
                  {gws.map((gw) => (
                    <th key={gw}>GW{gw}</th>
                  ))}
                  <th>Total</th>
                  <th>Base</th>
                  <th>Fixture</th>
                  <th>Trend</th>
                  <th>xMins</th>
                  <th>Own%</th>
                  <th className="left">Confidence</th>
                </>
              ) : null}
              {view === "sources" ? (
                <>
                  <th>Total</th>
                  {SOURCE_COLUMNS.map(([k, label]) => (
                    <th key={k}>{label}</th>
                  ))}
                </>
              ) : null}
              {view === "value" ? (
                <>
                  <th>Total</th>
                  <th>Pts per £m</th>
                  <th>Own%</th>
                  <th>Differential</th>
                  <th>Form</th>
                  <th>PPG</th>
                  <th>Δ price</th>
                  <th>Net transfers</th>
                  <th className="left">Set pieces</th>
                </>
              ) : null}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 250).map((p) => {
              const next = p.byGw[firstGw];
              const base = gws.reduce((s, gw) => s + Number(p.byGw[gw]?.base_score ?? 0), 0);
              const fix = gws.reduce((s, gw) => s + Number(p.byGw[gw]?.fixture_adjustment ?? 0), 0);
              const trend = gws.reduce((s, gw) => s + Number(p.byGw[gw]?.trend_adjustment ?? 0), 0);
              const conf = next?.confidence_breakdown?.confidence ?? "low";
              const isOpen = open === p.player_id;
              return (
                <Fragment key={p.player_id}>
                  <tr>
                    <td className="left">
                      <details className="player" open={isOpen}>
                        <summary
                          onClick={(e) => {
                            e.preventDefault();
                            setOpen(isOpen ? null : p.player_id);
                          }}
                        >
                          {p.web_name}
                          {p.status && p.status !== "a" ? (
                            <span className="flag" title={p.news ?? ""}> ⚠</span>
                          ) : null}
                        </summary>
                      </details>
                    </td>
                    <td className="left">{p.team}</td>
                    <td className="left">
                      <span className="pos">{POSITION_NAMES[p.position]}</span>
                    </td>
                    <td>{p.price.toFixed(1)}</td>
                    {view === "projection" ? (
                      <>
                        {gws.map((gw) => (
                          <td key={gw}>{num(Number(p.byGw[gw]?.final_score ?? 0))}</td>
                        ))}
                        <td><strong>{num(p.total)}</strong></td>
                        <td className="meta">{num(base)}</td>
                        <td><Delta value={fix} /></td>
                        <td><Delta value={trend} /></td>
                        <td>{num(Number(next?.expected_minutes ?? 0), 0)}</td>
                        <td className="meta">{p.selected_by_percent ?? "-"}</td>
                        <td className="left">
                          <span className={`pill ${conf}`}>{conf}</span>
                        </td>
                      </>
                    ) : null}
                    {view === "sources" ? (
                      <>
                        <td><strong>{num(p.total)}</strong></td>
                        {SOURCE_COLUMNS.map(([k]) => {
                          const v = p.sources[k] ?? 0;
                          const share = p.total > 0 ? v / p.total : 0;
                          return (
                            <td
                              key={k}
                              className={Math.abs(v) < 0.005 ? "meta" : ""}
                              title={`${(share * 100).toFixed(0)}% of projected points`}
                            >
                              {num(v)}
                            </td>
                          );
                        })}
                      </>
                    ) : null}
                    {view === "value" ? (
                      <>
                        <td><strong>{num(p.total)}</strong></td>
                        <td>{p.price > 0 ? num(p.total / p.price) : "-"}</td>
                        <td className="meta">{p.selected_by_percent ?? "-"}</td>
                        <td>
                          {num(p.total / Math.max(0.5, Number(p.selected_by_percent ?? 0)))}
                        </td>
                        <td className="meta">{p.form ?? "-"}</td>
                        <td className="meta">{p.points_per_game ?? "-"}</td>
                        <td>
                          <Delta value={Number(p.cost_change_start ?? 0) / 10} />
                        </td>
                        <td className="meta">
                          {(
                            (Number(p.transfers_in_event ?? 0) -
                              Number(p.transfers_out_event ?? 0)) / 1000
                          ).toFixed(0)}
                          k
                        </td>
                        <td className="left meta">
                          {p.penalties_order === 1 ? (
                            <span className="pill high">pens</span>
                          ) : null}{" "}
                          {p.direct_fk_order === 1 ? <span className="pill medium">FK</span> : null}{" "}
                          {p.corners_fk_order === 1 ? <span className="pill medium">corners</span> : null}
                        </td>
                      </>
                    ) : null}
                  </tr>
                  {isOpen && next ? (
                    <tr>
                      <td colSpan={14 + gws.length} className="left">
                        {p.news ? (
                          <div className="meta" style={{ marginBottom: 6 }}>
                            <strong className="flag">News:</strong> {p.news}
                          </div>
                        ) : null}
                        <Breakdown p={next} />
                      </td>
                    </tr>
                  ) : null}
                </Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
      {rows.length > 250 ? (
        <p className="meta">Showing the top 250 of {rows.length}. Narrow the filters to see more.</p>
      ) : null}
    </>
  );
}
