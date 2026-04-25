import { Suspense } from "react";
import { cookies } from "next/headers";
import { ProductionContent } from "./production-content";
import { serverGet } from "@/lib/server-api";
import type { CraftListResult, PackagingListResult, SummaryResult } from "./production-content";

function ProductionSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function ProductionPage() {
  let initialCraft: CraftListResult | undefined;
  let initialPackaging: PackagingListResult | undefined;
  let initialSummary: SummaryResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    const now = new Date();
    const year = String(now.getFullYear());
    const month = String(now.getMonth() + 1);
    [initialCraft, initialPackaging, initialSummary] = await Promise.all([
      serverGet<CraftListResult>("/production-summary/craft/list", cookieHeader, { year, month }),
      serverGet<PackagingListResult>("/production-summary/packaging/list", cookieHeader, { year, month }),
      serverGet<SummaryResult>("/production-summary/summary", cookieHeader, { year, month }),
    ]);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<ProductionSkeleton />}>
      <ProductionContent initialCraft={initialCraft} initialPackaging={initialPackaging} initialSummary={initialSummary} />
    </Suspense>
  );
}
