import { Suspense } from "react";
import { cookies } from "next/headers";
import { CustomerContent } from "./customer-content";
import { serverGet } from "@/lib/server-api";
import type { CustomerListResult } from "./customer-content";

function CustomerSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function CustomerPage() {
  let initialData: CustomerListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialData = await serverGet<CustomerListResult>("/customers/list", cookieHeader);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<CustomerSkeleton />}>
      <CustomerContent initialData={initialData} />
    </Suspense>
  );
}
