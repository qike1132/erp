/**
 * 通用表格页加载骨架屏
 * 适用于 approval, customer, finance, material, purchase, report, supplier, user 等页面
 */

export default function TableLoading() {
  return (
    <div className="space-y-4 p-6">
      {/* 标题 */}
      <div className="flex items-center justify-between">
        <div className="h-7 w-28 animate-pulse rounded bg-muted" />
        <div className="h-9 w-24 animate-pulse rounded bg-muted" />
      </div>

      {/* 筛选栏 */}
      <div className="flex gap-2">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="h-8 w-20 animate-pulse rounded bg-muted" />
        ))}
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
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="border-b px-3 py-2">
            <div className="flex gap-8">
              {Array.from({ length: 6 }).map((_, j) => (
                <div key={j} className="h-4 w-16 animate-pulse rounded bg-muted" />
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
