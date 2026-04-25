import { Suspense } from "react";
import { cookies } from "next/headers";
import { FinanceContent } from "./finance-content";
import { serverGet } from "@/lib/server-api";
import type { CustomerName } from "./finance-content";

function FinanceSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function FinancePage() {
  let initialCustomerNames: CustomerName[] | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialCustomerNames = await serverGet<CustomerName[]>("/customers/active-names", cookieHeader);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<FinanceSkeleton />}>
      <FinanceContent initialCustomerNames={initialCustomerNames} />
    </Suspense>
  );
}
