import Nav from "../Nav";
import { loadSquad } from "@/lib/squad";

export const dynamic = "force-dynamic";

export default async function TransfersPage() {
  const data = await loadSquad();
  const gws = data.gameweeks;

  const planSteps = data.suggestions
    .filter((s) => s.reasoning.plan)
    .sort((a, b) => a.reasoning.plan!.step - b.reasoning.plan!.step);
  const depth = planSteps[0]?.reasoning.plan?.recommended_depth ?? 0;
  const recommended = planSteps.filter((s) => s.reasoning.plan!.step <= depth);
  const recommendedNet =
    recommended.length > 0
      ? recommended[recommended.length - 1].reasoning.plan!.cumulative_net
      : 0;
  const fullNet =
    planSteps.length > 0 ? planSteps[planSteps.length - 1].reasoning.plan!.cumulative_net : 0;

  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">
          Transfers{data.hasSquad ? ` · GW${data.gw} · ${data.freeTransfers} free` : ""}
        </span>
      </header>
      <Nav current="/transfers" />

      {!data.hasSquad ? (
        <div className="banner">
          <strong>No squad imported</strong>
          <p style={{ margin: "6px 0 0" }}>Enter your 15 on the Squad page first.</p>
        </div>
      ) : data.suggestions.length === 0 ? (
        <div className="banner">
          <strong>No suggestions for the current squad</strong>
          <p style={{ margin: "6px 0 0" }}>
            Either nothing clears the minimum gain, or the squad changed since the planner
            last ran. Run <code>.venv/bin/python ingest/run.py plan</code>.
          </p>
        </div>
      ) : (
        <>
          <div className="banner">
            <strong>
              Recommended: {depth === 0 ? "no transfer" : `${depth} transfer${depth === 1 ? "" : "s"}`}
              {depth > 0 ? `, net ${recommendedNet >= 0 ? "+" : ""}${recommendedNet.toFixed(2)} points over ${gws.length} gameweeks` : ""}
            </strong>
            <p style={{ margin: "6px 0 0" }}>
              You have {data.freeTransfers} free transfer{data.freeTransfers === 1 ? "" : "s"};
              each one beyond that costs 4 points. Taking every affordable move in the plan
              below ({planSteps.length}) would net {fullNet >= 0 ? "+" : ""}
              {fullNet.toFixed(2)} — {fullNet < recommendedNet ? "worse" : "better"} than stopping at{" "}
              {depth}. Nothing here is executed for you.
            </p>
          </div>

          {planSteps.length > 0 ? (
            <>
              <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>The plan, in order</h2>
              <p className="meta" style={{ marginTop: 0 }}>
                A sequence you can actually execute: no player bought twice, no player sold
                twice, and the bank tracked at every step.
              </p>
              <div className="table-scroll" style={{ marginBottom: 26 }}>
                <table>
                  <thead>
                    <tr>
                      <th>#</th>
                      <th className="left">Out</th>
                      <th className="left">In</th>
                      <th>Cash</th>
                      <th>Bank after</th>
                      <th>Gross</th>
                      <th>Hit</th>
                      <th>Net</th>
                      <th>Cumulative</th>
                      <th className="left">Take it?</th>
                    </tr>
                  </thead>
                  <tbody>
                    {planSteps.map((s) => {
                      const p = s.reasoning.plan!;
                      const take = p.step <= depth;
                      return (
                        <tr key={s.id} className={take ? "plan-row" : ""}>
                          <td><span className="step">{p.step}</span></td>
                          <td className="left">
                            {s.reasoning.out.name} <span className="meta">({s.reasoning.out.team})</span>
                          </td>
                          <td className="left">
                            {s.reasoning.in.name} <span className="meta">({s.reasoning.in.team})</span>
                          </td>
                          <td className={s.cash_delta < 0 ? "neg-val" : "pos-val"}>
                            {(s.cash_delta / 10).toFixed(1)}
                          </td>
                          <td className="meta">{(p.bank_after / 10).toFixed(1)}</td>
                          <td>+{p.gross.toFixed(2)}</td>
                          <td className={p.marginal_hit ? "neg-val" : "meta"}>
                            {p.marginal_hit ? `-${p.marginal_hit}` : "0"}
                          </td>
                          <td className={p.net_after_hit >= 0 ? "pos-val" : "neg-val"}>
                            {p.net_after_hit >= 0 ? "+" : ""}
                            {p.net_after_hit.toFixed(2)}
                          </td>
                          <td><strong>{p.cumulative_net >= 0 ? "+" : ""}{p.cumulative_net.toFixed(2)}</strong></td>
                          <td className="left">
                            <span className={`pill ${take ? "high" : "low"}`}>{take ? "yes" : "no"}</span>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            </>
          ) : null}

          <h2 style={{ fontSize: 15, margin: "22px 0 8px" }}>Every option, ranked</h2>
          <p className="meta" style={{ marginTop: 0 }}>
            Each row is a single transfer taken on its own, so its hit is simply whether a
            free transfer is available. These are alternatives to each other, not a list to
            work down.
          </p>
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>#</th>
                  <th className="left">Out</th>
                  <th className="left">In</th>
                  <th>Out £</th>
                  <th>In £</th>
                  <th>Cash</th>
                  {gws.map((gw) => (
                    <th key={gw}>GW{gw}</th>
                  ))}
                  <th>Gross</th>
                  <th>Hit</th>
                  <th>Net</th>
                  <th className="left">Why</th>
                </tr>
              </thead>
              <tbody>
                {data.suggestions.map((s) => {
                  const r = s.reasoning;
                  const outPct = r.out.price_bracket_percentile;
                  const inPct = r.in.price_bracket_percentile;
                  return (
                    <tr key={s.id}>
                      <td className="meta">{s.rank}</td>
                      <td className="left">
                        {r.out.name} <span className="meta">({r.out.team})</span>
                        {r.out.in_best_xi ? (
                          <span className="xi-badge starter" style={{ marginLeft: 5 }}>XI</span>
                        ) : (
                          <span className="xi-badge" style={{ marginLeft: 5 }}>bench</span>
                        )}
                      </td>
                      <td className="left">
                        {r.in.name} <span className="meta">({r.in.team})</span>
                      </td>
                      <td>{(s.out_cost / 10).toFixed(1)}</td>
                      <td>{(s.in_cost / 10).toFixed(1)}</td>
                      <td className={s.cash_delta < 0 ? "neg-val" : "pos-val"}>
                        {(s.cash_delta / 10).toFixed(1)}
                      </td>
                      {gws.map((gw) => {
                        const d = r.per_gameweek[String(gw)];
                        if (!d) return <td key={gw} className="meta">—</td>;
                        const diff = d.in - d.out;
                        return (
                          <td key={gw} className={diff >= 0 ? "pos-val" : "neg-val"}>
                            {diff >= 0 ? "+" : ""}
                            {diff.toFixed(2)}
                          </td>
                        );
                      })}
                      <td>+{Number(s.gross_gain_3gw).toFixed(2)}</td>
                      <td className={s.hit_cost ? "neg-val" : "meta"}>
                        {s.hit_cost ? `-${s.hit_cost}` : "0"}
                      </td>
                      <td>
                        <strong className={Number(s.net_gain_3gw) >= 0 ? "pos-val" : "neg-val"}>
                          {Number(s.net_gain_3gw) >= 0 ? "+" : ""}
                          {Number(s.net_gain_3gw).toFixed(2)}
                        </strong>
                      </td>
                      <td className="left meta">
                        {r.out.name} ranks{" "}
                        {outPct === null ? "—" : `${Math.round(outPct * 100)}%`} among players
                        in the same position within £0.5m; {r.in.name} ranks{" "}
                        {inPct === null ? "—" : `${Math.round(inPct * 100)}%`}
                        {r.in.ownership !== null ? `, ${r.in.ownership}% owned` : ""}
                        {r.out.news ? ` · ${r.out.news}` : ""}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="meta" style={{ marginTop: 10 }}>
            Projections carry no trend adjustment — the trend engine failed its backtest, so
            these are base rates plus fixture difficulty only. Sale values assume you bought at
            today&rsquo;s price, since FPL publishes no purchase prices; if you bought earlier
            and cheaper you may have slightly more to spend than shown.
          </p>
        </>
      )}
    </main>
  );
}
