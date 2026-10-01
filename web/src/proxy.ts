import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = "lp_session";
const PUBLIC_PATHS = ["/login", "/register"];

// Optimistic gate only: it checks the cookie exists. The API verifies the token on every call,
// and a 401 from the API sends the user back to /login (see lib/api/client.ts).
export function proxy(request: NextRequest) {
  const { pathname, search } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const isPublic = PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(`${p}/`));

  if (!hasSession && !isPublic) {
    const url = new URL("/login", request.url);
    if (pathname !== "/") url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }
  if (hasSession && isPublic) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/((?!api/|_next/static|_next/image|favicon.ico|.*\\.(?:png|svg|jpg|webp|ico)$).*)"],
};
