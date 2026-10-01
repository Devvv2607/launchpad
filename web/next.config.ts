import type { NextConfig } from "next";

// The browser only ever talks to the Next origin; /api/v1/* is proxied to FastAPI.
// This keeps the session cookie first-party + httpOnly and avoids CORS in the browser.
const API_INTERNAL_URL = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  async rewrites() {
    return [{ source: "/api/v1/:path*", destination: `${API_INTERNAL_URL}/api/v1/:path*` }];
  },
};

export default nextConfig;
