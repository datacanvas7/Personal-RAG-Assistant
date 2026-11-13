import type { NextConfig } from "next";

// Where the Next.js *server* reaches the FastAPI service. Inside Docker Compose this is
// the service name. Rewrites are resolved at `next build` time and baked into the build,
// so the Dockerfile passes this value as a build argument.
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  // Emit a self-contained server (.next/standalone) so the production image does not
  // need node_modules.
  output: "standalone",
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
  // The browser only ever talks to this origin. /api/v1/* is proxied to FastAPI, which
  // means no CORS configuration, no API URL baked into client code, and the refresh
  // cookie (Phase 2) stays first-party.
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${backendInternalUrl}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
