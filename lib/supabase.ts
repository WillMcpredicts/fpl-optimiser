/**
 * Minimal PostgREST reader.
 *
 * The app only ever reads, and only from a handful of tables, so a full client
 * library would be more surface area than the job needs. Reads use the service
 * role key on the server; nothing here is exposed to the browser.
 */
const URL_BASE = (process.env.SUPABASE_URL ?? process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").replace(/\/$/, "");
const KEY =
  process.env.SUPABASE_SERVICE_ROLE_KEY ?? process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export function isConfigured(): boolean {
  return Boolean(URL_BASE && KEY);
}

export async function selectRows<T>(table: string, query: string): Promise<T[]> {
  if (!isConfigured()) throw new Error("Supabase is not configured");

  const out: T[] = [];
  const page = 1000;
  let offset = 0;

  // PostgREST caps a response at 1000 rows by default; page until short.
  for (;;) {
    const res = await fetch(
      `${URL_BASE}/rest/v1/${table}?${query}&limit=${page}&offset=${offset}`,
      {
        headers: { apikey: KEY, Authorization: `Bearer ${KEY}` },
        cache: "no-store",
      },
    );
    if (!res.ok) {
      throw new Error(`Supabase ${table} read failed (${res.status}): ${await res.text()}`);
    }
    const rows = (await res.json()) as T[];
    out.push(...rows);
    if (rows.length < page) return out;
    offset += page;
  }
}
