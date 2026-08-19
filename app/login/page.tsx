export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ error?: string; next?: string }>;
}) {
  const params = await searchParams;
  return (
    <form className="login" method="post" action="/api/login">
      <h1>FPL Optimiser</h1>
      {params.error ? <div className="err">Incorrect password.</div> : null}
      <input type="hidden" name="next" value={params.next ?? "/"} />
      <input
        type="password"
        name="password"
        placeholder="Password"
        autoFocus
        autoComplete="current-password"
      />
      <button type="submit">Sign in</button>
    </form>
  );
}
