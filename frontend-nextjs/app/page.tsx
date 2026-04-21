export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <h1 className="text-4xl font-bold mb-4">滨发协同系统</h1>
      <p className="text-lg text-secondary">Next.js 15 + React 19 重构版本</p>
      <div className="mt-8 flex gap-4">
        <a
          href="/dashboard"
          className="px-6 py-3 bg-primary text-white rounded-lg hover:bg-blue-700 transition"
        >
          进入仪表盘
        </a>
        <a
          href="/login"
          className="px-6 py-3 border border-primary text-primary rounded-lg hover:bg-blue-50 transition"
        >
          登录
        </a>
      </div>
    </main>
  );
}
