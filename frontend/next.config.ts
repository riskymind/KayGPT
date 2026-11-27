import type { NextConfig } from "next";

/**
 * BACKEND_URL: where the FastAPI service lives (server-side only, never sent to the browser).
 * The browser calls /api/v1/* on this origin and Next.js proxies it to the backend, so the
 * session cookie stays first-party (no third-party cookie problems between Vercel and Render).
 * Rewrites are resolved at build time: set BACKEND_URL for `next build` (Vercel env var, or
 * Docker build arg).
 */
const backendUrl = (process.env.BACKEND_URL ?? "http://localhost:8000").replace(/\/$/, "");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), geolocation=(), microphone=(self)" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Gzip in Next would buffer the proxied SSE stream; compression belongs to the edge/CDN.
  compress: false,
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${backendUrl}/api/v1/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
