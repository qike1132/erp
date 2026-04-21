export default function DashboardPage() {
  return (
    <div className="p-8">
      <h1 className="text-3xl font-bold mb-6">仪表盘</h1>
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard title="今日订单" value="128" trend="+12%" />
        <StatCard title="待审批" value="15" trend="-3%" />
        <StatCard title="库存预警" value="8" trend="+2%" />
        <StatCard title="本月营收" value="¥128,000" trend="+18%" />
      </div>
    </div>
  );
}

function StatCard({ title, value, trend }: { title: string; value: string; trend: string }) {
  const isPositive = trend.startsWith("+");
  return (
    <div className="bg-surface p-6 rounded-xl shadow-sm border">
      <h3 className="text-sm font-medium text-secondary">{title}</h3>
      <div className="mt-2 flex items-baseline gap-2">
        <span className="text-2xl font-bold">{value}</span>
        <span className={`text-sm ${isPositive ? "text-success" : "text-danger"}`}>
          {trend}
        </span>
      </div>
    </div>
  );
}
