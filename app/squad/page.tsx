import Nav from "../Nav";

export default function Page() {
  return (
    <main className="wrap">
      <header className="top">
        <h1>FPL Optimiser</h1>
        <span className="meta">Squad · arrives in Phase 3</span>
      </header>
      <Nav current="/squad" />
      <div className="banner">
        <strong>Not built yet — Phase 3</strong>
        <p style={{ margin: "6px 0 0" }}>Import your 15, score them against the model, and flag the weakest starting XI picks by predicted points against price.</p>
      </div>
    </main>
  );
}
