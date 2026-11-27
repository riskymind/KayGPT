import { NextResponse, type NextRequest } from "next/server";

const SESSION_COOKIE = process.env.SESSION_COOKIE_NAME ?? "kaygpt_session";
const AUTH_PAGES = ["/login", "/register"];

/**
 * Cheap routing guard: send visitors without a session cookie to /login, and signed-in
 * visitors away from the auth pages. The backend remains the authority (the client shell
 * also checks /auth/me and handles expired sessions).
 *
 * Only meaningful in same-origin mode; with NEXT_PUBLIC_API_URL set the cookie belongs to the
 * API domain and is invisible here, so the guard is skipped.
 */
export function proxy(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_API_URL) return NextResponse.next();

  const { pathname } = request.nextUrl;
  const hasSession = request.cookies.has(SESSION_COOKIE);
  const onAuthPage = AUTH_PAGES.some((p) => pathname.startsWith(p));

  if (!hasSession && !onAuthPage) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.search = pathname === "/" ? "" : `?next=${encodeURIComponent(pathname)}`;
    return NextResponse.redirect(url);
  }
  if (hasSession && onAuthPage) {
    return NextResponse.redirect(new URL("/", request.url));
  }
  return NextResponse.next();
}

export const config = {
  // Skip API proxying, Next internals and static files.
  matcher: ["/((?!api/|_next/|favicon.ico|.*\\.(?:png|svg|ico|webp|txt)$).*)"],
};
