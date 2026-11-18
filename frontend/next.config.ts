import type { NextConfig } from "next";

// Where the Next.js *server* reaches the FastAPI service. Inside Docker Compose this is
// the service name. Rewrites are resolved at `next build` time and baked into the build,
// so the Dockerfile passes this value as a build argument.
const backendInternalUrl = process.env.BACKEND_INTERNAL_URL ?? "http://localhost:8000";

// Headers for every page (not for /api/v1, whose responses carry the API's own).
// The CSP allows inline scripts because Next.js emits inline bootstrap scripts; a nonce-based
// policy would be stricter but forces fully dynamic rendering (see docs/operations.md).
// 'unsafe-eval' is development-only (React Refresh). HSTS belongs at the TLS terminator.
const isProduction = process.env.NODE_ENV === "production";
const contentSecurityPolicy = [
  "default-src 'self'",
  `script-src 'self' 'unsafe-inline'${isProduction ? "" : " 'unsafe-eval'"}`,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob:",
  "font-src 'self' data:",
  "connect-src 'self'",
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), payment=()" },
  ...(isProduction ? [{ key: "Content-Security-Policy", value: contentSecurityPolicy }] : []),
];

const nextConfig: NextConfig = {
  // Emit a self-contained server (.next/standalone) so the production image does not
  // need node_modules.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  experimental: {
    // Proxied request bodies are cut off at 10 MB by default, which silently breaks uploads
    // between 10 and 25 MB (the API's MAX_UPLOAD_BYTES). Allow a little more than the API's
    // limit so oversized files reach FastAPI and get its clear 413 instead of a dropped socket.
    proxyClientMaxBodySize: "30mb",
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async headers() {
    return [{ source: "/((?!api/).*)", headers: securityHeaders }];
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
