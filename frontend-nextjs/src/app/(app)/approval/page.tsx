import { Suspense } from "react";
import { cookies } from "next/headers";
import { ApprovalContent } from "./approval-content";
import { serverGet } from "@/lib/server-api";
import type { ApprovalListResult } from "./approval-content";

function ApprovalSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function ApprovalPage() {
  let initialData: ApprovalListResult | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    initialData = await serverGet<ApprovalListResult>("/approvals/list", cookieHeader, {
      status: "pending",
      page: "1",
      per_page: "20",
    });
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<ApprovalSkeleton />}>
      <ApprovalContent initialData={initialData} />
    </Suspense>
  );
}
