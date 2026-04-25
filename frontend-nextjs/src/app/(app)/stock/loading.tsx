/**
 * 库存管理加载骨架屏
 */

export default function StockLoading() {
  return (
    <div className="space-y-4 p-6">
      <div className="h-7 w-28 animate-pulse rounded bg-muted" />

      {/* Tab 按钮 */}
      <div className="flex gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-8 w-20 animate-pulse rounded bg-muted" />
        ))}
      </div>

      {/* 操作栏 */}
      <div className="flex justify-end">
        <div className="h-9 w-24 animate-pulse rounded bg-muted" />
      </div>

      {/* 表格骨架 */}
      <div className="rounded-md border">
        <div className="border-b bg-muted/50 px-3 py-2">
          <div className="flex gap-8">
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="h-4 w-14 animate-pulse rounded bg-muted" />
            ))}
          </div>
        </div>
        {Array.from({ length: 8 }).map((_, i) => (
          <div key={i} className="border-b px-3 py-2">
            <div className="flex gap-8">
              <div className="h-4 w-24 animate-pulse rounded bg-muted" />
              <div className="h-4 w-20 animate-pulse rounded bg-muted" />
              <div className="h-4 w-16 animate-pulse rounded bg-muted" />
              <div className="h-4 w-10 animate-pulse rounded bg-muted" />
              <div className="h-4 w-20 animate-pulse rounded bg-muted" />
              <div className="h-4 w-16 animate-pulse rounded bg-muted" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
