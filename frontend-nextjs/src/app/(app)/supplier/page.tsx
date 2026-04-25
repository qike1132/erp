import { Suspense } from "react";
import { cookies } from "next/headers";
import { SupplierContent } from "./supplier-content";
import { serverGet } from "@/lib/server-api";
import type { SupplierListResult } from "./supplier-content";

function SupplierSkeleton() {
  return (
    <div className="sp-page-root">
      <div className="container-fluid">
        <div className="page-header-wrapper">
          <h2 className="page-title">供应商管理</h2>
          <p className="page-subtitle">管理供应商信息，支持添加、编辑、删除供应商</p>
        </div>
        <div style={{ padding: 40, textAlign: "center", color: "var(--plush-text-light, #718096)" }}>
          <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
          <p style={{ marginTop: 12 }}>加载中...</p>
        </div>
      </div>
    </div>
  );
}

export default async function SupplierPage() {
  let initialData: SupplierListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialData = await serverGet<SupplierListResult>(
      "/suppliers/list",
      cookieHeader
    );
  } catch {
    // SSR fetch failed — client will retry via useQuery
  }

  return (
    <Suspense fallback={<SupplierSkeleton />}>
      <SupplierContent initialData={initialData} />
    </Suspense>
  );
}
