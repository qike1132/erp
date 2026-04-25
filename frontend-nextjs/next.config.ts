import type { NextConfig } from "next";

const isDev = process.env.NODE_ENV === "development";

const nextConfig: NextConfig = {
  // Docker-ready standalone output
  output: isDev ? undefined : "standalone",

  poweredByHeader: false,

  // React Compiler: 在生产环境启用以获得最佳开发体验
  reactCompiler: !isDev,

  // Tree-shake heavy packages
  experimental: {
    optimizePackageImports: [
      "lucide-react",
      "@base-ui/react",
      "@tanstack/react-table",
      "@tanstack/react-query",
      "class-variance-authority",
    ],
    // 开发环境优化：禁用某些实验性功能以提高热更新速度
    ...(isDev && {
      optimizeCss: false,
    }),
  },

  // 开发环境性能优化配置
  ...(isDev && {
    typescript: {
      ignoreBuildErrors: false,
    },
    eslint: {
      ignoreDuringBuilds: true,
    },
  }),

  // Security headers - CSP (开发环境放宽限制，生产环境严格)
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              // 开发环境: 允许内联脚本以支持 HMR
              // Next.js RSC 需要内联脚本传递数据，生产环境也必须允许 'unsafe-inline'
              isDev ? "script-src 'self' 'unsafe-inline' 'unsafe-eval'" : "script-src 'self' 'unsafe-inline'",
              isDev ? "style-src 'self' 'unsafe-inline'" : "style-src 'self' 'unsafe-inline'",
              "img-src 'self' data: blob:",
              "font-src 'self'",
              // 生产环境 connect-src 仅需 'self'（API 通过 rewrites 代理为同源）
              // 开发环境额外允许直连后端
              isDev ? "connect-src 'self' http://localhost:5002 http://127.0.0.1:5002" : "connect-src 'self'",
              "frame-ancestors 'none'",
              "form-action 'self'",
              "base-uri 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },

  // FastAPI backend proxy for API routes
  // 使用环境变量 BACKEND_INTERNAL_URL（Docker 内网地址）或默认 localhost:5002
  async rewrites() {
    const backendUrl = process.env.BACKEND_INTERNAL_URL || "http://127.0.0.1:5002";
    return [
      {
        source: "/api/:path*",
        destination: `${backendUrl}/api/:path*`,
      },
    ];
  },

  // Turbopack config
  turbopack: {},
};

export default nextConfig;
