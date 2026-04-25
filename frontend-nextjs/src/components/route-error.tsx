/**
 * 通用路由级错误边界
 *
 * Next.js error.tsx 必须是 "use client" 组件。
 * 捕获该路由及子路由的运行时错误，提供重试按钮。
 */
"use client";

import { useEffect } from "react";

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("[RouteError]", error);
  }, [error]);

  return (
    <div className="flex min-h-[40vh] items-center justify-center">
      <div className="text-center">
        <h2 className="text-lg font-semibold text-destructive">加载失败</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          {error.message || "数据加载出错，请重试"}
        </p>
        <button
          onClick={reset}
          className="mt-3 rounded-md bg-primary px-4 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary/90"
        >
          重试
        </button>
      </div>
    </div>
  );
}
