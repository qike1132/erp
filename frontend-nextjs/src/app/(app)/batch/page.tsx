import { Suspense } from "react";
import { cookies } from "next/headers";
import { BatchContent } from "./batch-content";
import { serverGet } from "@/lib/server-api";
import type { BatchStats, BatchListResult } from "./batch-content";

function BatchSkeleton() {
  return (
    <div className="sb-wrap">
      <div style={{ padding: 40, textAlign: "center", color: "var(--sb-text3, #A0AEC0)" }}>
        <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
        <p style={{ marginTop: 12 }}>加载中...</p>
      </div>
    </div>
  );
}

export default async function BatchPage() {
  let initialStats: BatchStats | undefined;
  let initialList: BatchListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    [initialStats, initialList] = await Promise.all([
      serverGet<BatchStats>("/sku-batches/stats", cookieHeader),
      serverGet<BatchListResult>("/sku-batches/batches", cookieHeader, {
        page: "1",
        per_page: "20",
        sort_by: "create_time",
        sort_order: "desc",
      }),
    ]);
  } catch {
    // SSR fetch failed — client will retry via useQuery
  }

  return (
    <Suspense fallback={<BatchSkeleton />}>
      <BatchContent initialStats={initialStats} initialList={initialList} />
    </Suspense>
  );
}
