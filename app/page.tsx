import Nav from "./Nav";
import PlayerTable from "./PlayerTable";
import { loadDataset } from "@/lib/data";

export const dynamic = "force-dynamic";

export default async function Home() {
  const data = await loadDataset();

  const sourceLabel =
    data.source === "supabase"
      ? "Supabase"
      : data.source === "snapshot"
        ? "local snapshot (Supabase not in use)"
        : "no data";

  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">
          Phase 1 · model {data.modelVersion ?? "—"} · source: {sourceLabel}
          {data.generatedAt
            ? ` · computed ${new Date(data.generatedAt).toLocaleString("en-GB")}`
            : ""}
        </span>
      </header>

      <Nav current="/" />

      {data.warnings.length > 0 ? (
        <div className="banner">
          <strong>Read this before trusting the numbers</strong>
          <ul>
            {data.warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {data.players.length === 0 ? (
        <p>
          No predictions available yet. Run the ingestion, or generate a local snapshot
          with <code>.venv/bin/python ingest/dryrun.py 3 --snapshot</code>.
        </p>
      ) : (
        <>
          <p className="meta" style={{ marginTop: 0 }}>
            Every score is <code>base + fixture + trend</code>. Click a player to see the
            breakdown. The trend term is opponent generosity to that position, worth
            +0.46% on held-out data over the fixture adjustment alone, capped at 15% and
            never applied to forwards. Switch the view to see where points come from, or
            value and price.
          </p>
          <PlayerTable data={data} />
        </>
      )}
    </main>
  );
}
