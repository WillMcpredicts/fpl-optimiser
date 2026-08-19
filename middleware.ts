import { NextResponse, type NextRequest } from "next/server";

import { COOKIE_NAME, gateDisabled, isValidToken } from "./lib/auth";

export async function middleware(request: NextRequest) {
  if (gateDisabled()) return NextResponse.next();

  const token = request.cookies.get(COOKIE_NAME)?.value;
  if (await isValidToken(token)) return NextResponse.next();

  const url = request.nextUrl.clone();
  url.pathname = "/login";
  url.searchParams.set("next", request.nextUrl.pathname);
  return NextResponse.redirect(url);
}

export const config = {
  // Everything except the login route, the login API and Next's own assets.
  matcher: ["/((?!login|api/login|_next/static|_next/image|favicon.ico).*)"],
};
