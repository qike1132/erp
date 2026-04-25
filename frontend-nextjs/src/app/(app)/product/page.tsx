import { Suspense } from "react";
import { cookies } from "next/headers";
import { ProductListContent } from "./product-list-content";
import { serverGet } from "@/lib/server-api";
import type { ProductListResult } from "./product-list-content";

function ProductListSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function ProductListPage() {
  let initialData: ProductListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialData = await serverGet<ProductListResult>("/products/list", cookieHeader, {
      page: "1",
      per_page: "20",
    });
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<ProductListSkeleton />}>
      <ProductListContent initialData={initialData} />
    </Suspense>
  );
}
