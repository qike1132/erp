import { Suspense } from "react";
import { cookies } from "next/headers";
import { CustomerOrderContent } from "./customer-order-content";
import { serverGet } from "@/lib/server-api";
import type { ListResult } from "./customer-order-content";
import type { OrderItem, StockinItem } from "./customer-order-content";

interface Customer { id: number; name: string; }

function CustomerOrderSkeleton() {
  return (
    <div style={{ padding: 40, textAlign: "center", color: "#718096" }}>
      <i className="fas fa-spinner fa-spin" style={{ fontSize: 24 }}></i>
      <p style={{ marginTop: 12 }}>加载中...</p>
    </div>
  );
}

export default async function CustomerOrderPage() {
  let initialOrders: ListResult<OrderItem> | undefined;
  let initialStockins: ListResult<StockinItem> | undefined;
  let initialCustomers: ListResult<Customer> | undefined;
  try {
    const cookieStore = await cookies();
    const cookieHeader = cookieStore
      .getAll()
      .map((c) => `${c.name}=${c.value}`)
      .join("; ");
    [initialOrders, initialStockins, initialCustomers] = await Promise.all([
      serverGet<ListResult<OrderItem>>("/orders/list", cookieHeader, { per_page: "5000" }),
      serverGet<ListResult<StockinItem>>("/stock/in/list", cookieHeader, { per_page: "5000" }),
      serverGet<ListResult<Customer>>("/customers/list", cookieHeader),
    ]);
  } catch {
    // SSR fetch failed — client will retry
  }

  return (
    <Suspense fallback={<CustomerOrderSkeleton />}>
      <CustomerOrderContent initialOrders={initialOrders} initialStockins={initialStockins} initialCustomers={initialCustomers} />
    </Suspense>
  );
}
