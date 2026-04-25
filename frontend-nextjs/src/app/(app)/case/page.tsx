import { Suspense } from "react";
import { cookies } from "next/headers";
import { CaseContent } from "./case-content";
import { serverGet } from "@/lib/server-api";
import type { PaginatedData } from "./case-content";
import type { StockinRecord, StockoutRecord, InventoryItem } from "./case-content";

function CaseSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function CasePage() {
  let initialCustomers: string[] | undefined;
  let initialStockins: PaginatedData<StockinRecord> | undefined;
  let initialStockouts: PaginatedData<StockoutRecord> | undefined;
  let initialInventory: InventoryItem[] | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    [initialCustomers, initialStockins, initialStockouts, initialInventory] = await Promise.all([
      serverGet<string[]>("/customers/active-names", cookieHeader),
      serverGet<PaginatedData<StockinRecord>>("/cases/in/list", cookieHeader, { page: "1", per_page: "10" }),
      serverGet<PaginatedData<StockoutRecord>>("/cases/out/list", cookieHeader, { page: "1", per_page: "10" }),
      serverGet<InventoryItem[]>("/cases/inventory-summary", cookieHeader),
    ]);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<CaseSkeleton />}>
      <CaseContent
        initialCustomers={initialCustomers}
        initialStockins={initialStockins}
        initialStockouts={initialStockouts}
        initialInventory={initialInventory}
      />
    </Suspense>
  );
}
