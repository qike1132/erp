import { Suspense } from "react";
import { cookies } from "next/headers";
import { StockContent } from "./stock-content";
import { serverGet } from "@/lib/server-api";
import type { PageResult } from "./stock-content";
import type { StockInRecord } from "./stock-content";

function StockSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function StockPage() {
  let initialStockins: PageResult<StockInRecord> | undefined;
  let initialCustomers: { success: boolean; data: { id: number; name: string }[] } | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    [initialStockins, initialCustomers] = await Promise.all([
      serverGet<PageResult<StockInRecord>>("/stock/in/list", cookieHeader, { page: "1", per_page: "20" }),
      serverGet<{ success: boolean; data: { id: number; name: string }[] }>("/customers/list", cookieHeader),
    ]);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<StockSkeleton />}>
      <StockContent initialStockins={initialStockins} initialCustomers={initialCustomers} />
    </Suspense>
  );
}
