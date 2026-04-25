"use client";

import { useState, useEffect, Suspense } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuthStore } from "@/stores/auth-store";
import { post, get } from "@/lib/api-client";
import {
  BoxesIcon,
  FileTextIcon,
  BarChart3Icon,
  UserIcon,
  LockIcon,
  LogInIcon,
  AlertCircleIcon,
  CheckIcon,
  Loader2Icon,
} from "lucide-react";

/* ================================================================
   滨发玩具协同系统 - 登录页面
   完全还原原始 Jinja2 login.html 设计
   ================================================================ */

function BrandSection() {
  const features = [
    {
      icon: <BoxesIcon className="h-6 w-6" />,
      title: "智能库存管理",
      desc: "实时追踪库存动态，精准预测需求",
    },
    {
      icon: <FileTextIcon className="h-6 w-6" />,
      title: "高效订单处理",
      desc: "自动化流程，提升运营效率",
    },
    {
      icon: <BarChart3Icon className="h-6 w-6" />,
      title: "实时数据分析",
      desc: "可视化报表，洞察业务趋势",
    },
  ];

  return (
    <div className="brand-section">
      {/* 装饰性渐变背景 - 右上 */}
      <div
        className="pointer-events-none absolute"
        style={{
          top: "-195px",
          right: "-195px",
          width: "520px",
          height: "520px",
          background: "radial-gradient(circle, #D4F1F4 0%, transparent 70%)",
          opacity: 0.6,
        }}
      />
      {/* 装饰性渐变背景 - 左下 */}
      <div
        className="pointer-events-none absolute"
        style={{
          bottom: "-130px",
          left: "-130px",
          width: "390px",
          height: "390px",
          background: "radial-gradient(circle, #B0E0E6 0%, transparent 70%)",
          opacity: 0.4,
        }}
      />

      <div className="brand-content">
        {/* Logo */}
        <div className="logo-wrapper">
          <div className="logo-frame">
            <img
              src="/static/logo_plush.png"
              alt="滨发玩具"
              style={{
                width: "100%",
                height: "100%",
                objectFit: "contain",
                borderRadius: "50%",
              }}
            />
          </div>
        </div>

        {/* 品牌信息 */}
        <div className="brand-info">
          <h1 className="brand-title">滨发玩具协同系统</h1>
          <p className="brand-tagline">
            专业的毛绒玩具企业供应链管理平台
            <br />
            智能、高效、可靠的数字化管理解决方案
          </p>
        </div>

        {/* 功能卡片 */}
        <div className="feature-cards">
          {features.map((f, i) => (
            <div key={i} className="feature-card">
              <div className="feature-icon-wrap">{f.icon}</div>
              <div className="feature-text">
                <div className="feature-title">{f.title}</div>
                <div className="feature-desc">{f.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

function LoginForm() {
  return (
    <Suspense
      fallback={
        <div
          style={{
            display: "flex",
            minHeight: "100vh",
            width: "100%",
            alignItems: "center",
            justifyContent: "center",
            background: "#FAFBFC",
          }}
        >
          加载中...
        </div>
      }
    >
      <LoginFormInner />
    </Suspense>
  );
}

function LoginFormInner() {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(false);

  useEffect(() => {
    const saved = localStorage.getItem("remember_me") === "true";
    if (saved) setRemember(true);
  }, []);

  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [fieldErrors, setFieldErrors] = useState<{
    username?: string;
    password?: string;
  }>({});

  const setUser = useAuthStore((s) => s.setUser);
  const router = useRouter();
  const searchParams = useSearchParams();
  const redirectTo = searchParams.get("redirect") || "/dashboard";

  const handleRememberChange = (checked: boolean) => {
    setRemember(checked);
    localStorage.setItem("remember_me", String(checked));
  };

  function validate(): boolean {
    const errors: { username?: string; password?: string } = {};
    if (!username.trim()) {
      errors.username = "请输入用户名";
    } else if (username.trim().length < 2) {
      errors.username = "用户名至少2个字符";
    }
    if (!password) {
      errors.password = "请输入密码";
    } else if (password.length < 6) {
      errors.password = "密码至少6个字符";
    } else if (password.length > 128) {
      errors.password = "密码不能超过128个字符";
    }
    setFieldErrors(errors);
    return Object.keys(errors).length === 0;
  }

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    setFieldErrors({});
    if (!validate()) return;

    setLoading(true);
    try {
      await post("/auth/login", {
        username: username.trim(),
        password,
        remember,
      });
      const userInfo = await get<{
        user_id: number;
        username: string;
        is_super: boolean;
        permissions: string[];
      }>("/auth/me");
      setUser({
        id: userInfo.user_id,
        username: userInfo.username,
        isSuper: userInfo.is_super,
        permissions: userInfo.permissions,
      });
      router.push(redirectTo);
    } catch (err: unknown) {
      const apiErr = err as { detail?: string; message?: string };
      setError(
        apiErr.detail || apiErr.message || "登录失败，请检查用户名和密码"
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="login-section">
      <div className="login-card">
        {/* 标题 */}
        <div className="login-card-header">
          <h2 className="login-heading">欢迎登录</h2>
          <p className="login-subheading">请输入您的账号信息以访问系统</p>
        </div>

        <form onSubmit={handleSubmit} noValidate>
          {/* 错误提示 */}
          {error && (
            <div className="alert-box alert-error">
              <AlertCircleIcon className="h-5 w-5 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {/* 用户名 */}
          <div className="form-group">
            <label className="form-label" htmlFor="username">
              用户名
            </label>
            <div className="input-wrapper">
              <input
                id="username"
                type="text"
                value={username}
                onChange={(e) => {
                  setUsername(e.target.value);
                  if (fieldErrors.username)
                    setFieldErrors((prev) => ({ ...prev, username: undefined }));
                }}
                placeholder="请输入用户名"
                autoComplete="username"
                autoFocus
                className="form-input"
                aria-invalid={!!fieldErrors.username}
              />
              <UserIcon className="input-prefix" />
            </div>
            {fieldErrors.username && (
              <p className="field-error">{fieldErrors.username}</p>
            )}
          </div>

          {/* 密码 */}
          <div className="form-group">
            <label className="form-label" htmlFor="password">
              密码
            </label>
            <div className="input-wrapper">
              <input
                id="password"
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  if (fieldErrors.password)
                    setFieldErrors((prev) => ({ ...prev, password: undefined }));
                }}
                placeholder="请输入密码"
                autoComplete="current-password"
                className="form-input"
                aria-invalid={!!fieldErrors.password}
              />
              <LockIcon className="input-prefix" />
            </div>
            {fieldErrors.password && (
              <p className="field-error">{fieldErrors.password}</p>
            )}
          </div>

          {/* 记住我 */}
          <div className="remember-row">
            <label className="custom-checkbox">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => handleRememberChange(e.target.checked)}
              />
              <span className="checkbox-mark">
                <CheckIcon className="h-3.5 w-3.5 text-white" />
              </span>
              <span className="checkbox-label">记住我</span>
            </label>
          </div>

          {/* 登录按钮 */}
          <button type="submit" disabled={loading} className="btn-login">
            {loading ? (
              <>
                <Loader2Icon className="mr-2.5 inline-block h-5 w-5 animate-spin" />
                登录中...
              </>
            ) : (
              <>
                <LogInIcon className="mr-2.5 inline-block h-5 w-5" />
                安全登录
              </>
            )}
          </button>
        </form>

        {/* 页脚 */}
        <div className="login-footer">
          <p className="footer-text">滨发玩具供应链管理系统</p>
          <p className="footer-version">v2.0</p>
        </div>
      </div>
    </div>
  );
}

export default function LoginPage() {
  return (
    <div className="login-container">
      <BrandSection />
      <LoginForm />

      <style jsx global>{`
        /* ================================================================
           登录页面样式 - 完全还原原始 Jinja2 login.html
           ================================================================ */

        /* ---- 根变量 ---- */
        .login-container {
          --white: #ffffff;
          --off-white: #fafbfc;
          --light-gray: #f0f2f5;
          --border-light: #e8ecf0;
          --text-primary: #2d3748;
          --text-secondary: #718096;
          --text-muted: #a0aec0;
          --accent: #b0e0e6;
          --accent-light: #d4f1f4;
          --accent-dark: #87ceeb;
          --accent-gradient: linear-gradient(135deg, #87ceeb 0%, #b0e0e6 100%);
          --shadow-xs: 0 1px 2px rgba(0, 0, 0, 0.04);
          --shadow-sm: 0 2px 8px rgba(0, 0, 0, 0.06);
          --shadow-md: 0 4px 16px rgba(0, 0, 0, 0.08);
          --shadow-lg: 0 8px 32px rgba(0, 0, 0, 0.1);
          --shadow-xl: 0 16px 48px rgba(0, 0, 0, 0.12);
          --radius-sm: 8px;
          --radius-md: 12px;
          --radius-lg: 20px;
          --radius-xl: 28px;
          --transition-fast: 0.2s ease;
          --transition-normal: 0.3s ease;
          --transition-slow: 0.4s ease;
        }

        /* ---- 布局 ---- */
        .login-container {
          display: flex;
          width: 100%;
          min-height: 100vh;
          font-family: "Noto Sans SC", "Microsoft YaHei", -apple-system,
            BlinkMacSystemFont, sans-serif;
        }

        /* ---- 品牌区 ---- */
        .brand-section {
          flex: 1.1;
          background: var(--white);
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          padding: 78px;
          position: relative;
          overflow: hidden;
        }

        .brand-content {
          position: relative;
          z-index: 1;
          text-align: center;
          max-width: 546px;
        }

        /* Logo */
        .logo-wrapper {
          margin-bottom: 62px;
          animation: fadeInDown 0.8s ease;
        }

        .logo-frame {
          width: 182px;
          height: 182px;
          margin: 0 auto;
          background: var(--white);
          border-radius: 50%;
          padding: 21px;
          box-shadow: var(--shadow-lg);
          border: 5px solid var(--accent-light);
          transition: transform var(--transition-slow),
            box-shadow var(--transition-slow);
        }

        .logo-frame:hover {
          transform: scale(1.05);
          box-shadow: var(--shadow-xl);
        }

        /* 品牌信息 */
        .brand-info {
          animation: fadeInUp 0.8s ease 0.2s both;
        }

        .brand-title {
          font-size: 42px;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 16px;
          letter-spacing: -0.5px;
        }

        .brand-tagline {
          font-size: 20px;
          color: var(--text-secondary);
          line-height: 1.7;
          margin-bottom: 62px;
        }

        /* 功能卡片 */
        .feature-cards {
          display: flex;
          flex-direction: column;
          gap: 21px;
          animation: fadeInUp 0.8s ease 0.4s both;
        }

        .feature-card {
          display: flex;
          align-items: center;
          gap: 21px;
          padding: 26px 31px;
          background: var(--off-white);
          border-radius: var(--radius-lg);
          border: 1px solid var(--border-light);
          transition: all var(--transition-normal);
          box-shadow: var(--shadow-sm);
        }

        .feature-card:hover {
          background: var(--white);
          border-color: var(--accent);
          box-shadow: var(--shadow-md);
          transform: translateX(10px);
        }

        .feature-icon-wrap {
          width: 62px;
          height: 62px;
          background: var(--accent-gradient);
          border-radius: var(--radius-md);
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--white);
          font-size: 23px;
          box-shadow: var(--shadow-sm);
          flex-shrink: 0;
        }

        .feature-text {
          flex: 1;
          text-align: left;
        }

        .feature-title {
          font-size: 18px;
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 3px;
        }

        .feature-desc {
          font-size: 16px;
          color: var(--text-muted);
        }

        /* ---- 登录区 ---- */
        .login-section {
          flex: 1;
          display: flex;
          flex-direction: column;
          justify-content: center;
          align-items: center;
          padding: 78px;
          background: var(--off-white);
        }

        .login-card {
          width: 100%;
          max-width: 546px;
          background: var(--white);
          border-radius: var(--radius-xl);
          padding: 62px 57px;
          box-shadow: var(--shadow-lg);
          animation: fadeInUp 0.8s ease;
        }

        .login-card-header {
          text-align: center;
          margin-bottom: 52px;
        }

        .login-heading {
          font-size: 34px;
          font-weight: 700;
          color: var(--text-primary);
          margin-bottom: 10px;
        }

        .login-subheading {
          font-size: 18px;
          color: var(--text-secondary);
        }

        /* 表单 */
        .form-group {
          margin-bottom: 31px;
        }

        .form-label {
          display: block;
          font-size: 17px;
          font-weight: 600;
          color: var(--text-primary);
          margin-bottom: 13px;
        }

        .input-wrapper {
          position: relative;
        }

        .input-prefix {
          position: absolute;
          left: 21px;
          top: 50%;
          transform: translateY(-50%);
          color: var(--accent-dark);
          font-size: 21px;
          z-index: 2;
          transition: color var(--transition-fast);
          pointer-events: none;
          width: 21px;
          height: 21px;
        }

        .form-input {
          width: 100%;
          padding: 21px 23px 21px 65px;
          font-size: 18px;
          font-family: inherit;
          color: var(--text-primary);
          background: var(--off-white);
          border: 2px solid var(--border-light);
          border-radius: var(--radius-md);
          outline: none;
          transition: all var(--transition-fast);
        }

        .form-input::placeholder {
          color: var(--text-muted);
        }

        .form-input:focus {
          border-color: var(--accent-dark);
          background: var(--white);
          box-shadow: 0 0 0 4px rgba(176, 224, 230, 0.2);
        }

        .form-input:focus ~ .input-prefix,
        .input-wrapper:focus-within .input-prefix {
          color: var(--accent-dark);
        }

        .field-error {
          margin-top: 8px;
          font-size: 14px;
          color: #c53030;
        }

        /* 记住我 */
        .remember-row {
          display: flex;
          justify-content: space-between;
          align-items: center;
          margin-bottom: 36px;
        }

        .custom-checkbox {
          display: flex;
          align-items: center;
          gap: 13px;
          cursor: pointer;
        }

        .custom-checkbox input {
          display: none;
        }

        .checkbox-mark {
          width: 29px;
          height: 29px;
          border: 2px solid var(--border-light);
          border-radius: 8px;
          display: flex;
          align-items: center;
          justify-content: center;
          transition: all var(--transition-fast);
          background: var(--white);
        }

        .checkbox-mark svg {
          opacity: 0;
          transform: scale(0.5);
          transition: opacity 0.2s ease, transform 0.2s ease;
        }

        .custom-checkbox input:checked + .checkbox-mark {
          background: var(--accent-gradient);
          border-color: var(--accent-dark);
        }

        .custom-checkbox input:checked + .checkbox-mark svg {
          opacity: 1;
          transform: scale(1);
        }

        .checkbox-label {
          font-size: 17px;
          color: var(--text-secondary);
        }

        /* 登录按钮 */
        .btn-login {
          width: 100%;
          padding: 21px 31px;
          font-size: 20px;
          font-weight: 600;
          font-family: inherit;
          color: var(--white);
          background: var(--accent-gradient);
          border: none;
          border-radius: var(--radius-md);
          cursor: pointer;
          transition: all var(--transition-normal);
          box-shadow: var(--shadow-md);
          position: relative;
          overflow: hidden;
          letter-spacing: 0.5px;
        }

        .btn-login::before {
          content: "";
          position: absolute;
          top: 0;
          left: -100%;
          width: 100%;
          height: 100%;
          background: linear-gradient(
            90deg,
            transparent,
            rgba(255, 255, 255, 0.3),
            transparent
          );
          transition: left 0.6s ease;
        }

        .btn-login:hover {
          transform: translateY(-3px);
          box-shadow: var(--shadow-lg);
        }

        .btn-login:hover::before {
          left: 100%;
        }

        .btn-login:active {
          transform: translateY(0);
        }

        .btn-login:disabled {
          transform: none;
          cursor: not-allowed;
          opacity: 0.8;
        }

        /* 提示框 */
        .alert-box {
          padding: 18px 21px;
          border-radius: 12px;
          margin-bottom: 31px;
          display: flex;
          align-items: center;
          gap: 16px;
          font-size: 17px;
          animation: slideIn 0.4s ease;
        }

        .alert-error {
          background: #fef2f2;
          color: #c53030;
          border: 1px solid #fca5a5;
        }

        /* 页脚 */
        .login-footer {
          text-align: center;
          margin-top: 47px;
          padding-top: 36px;
          border-top: 1px solid var(--border-light);
        }

        .footer-text {
          font-size: 16px;
          color: var(--text-muted);
        }

        .footer-version {
          font-size: 14px;
          color: var(--text-muted);
          margin-top: 5px;
        }

        /* ---- 动画 ---- */
        @keyframes fadeInDown {
          from {
            opacity: 0;
            transform: translateY(-30px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes fadeInUp {
          from {
            opacity: 0;
            transform: translateY(20px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        @keyframes slideIn {
          from {
            opacity: 0;
            transform: translateY(-12px);
          }
          to {
            opacity: 1;
            transform: translateY(0);
          }
        }

        /* ---- 响应式 ---- */
        @media (max-width: 1024px) {
          .brand-section {
            padding: 48px;
          }

          .logo-frame {
            width: 120px;
            height: 120px;
          }

          .brand-title {
            font-size: 28px;
          }

          .login-section {
            padding: 48px;
          }

          .login-card {
            padding: 40px 36px;
          }
        }

        @media (max-width: 768px) {
          .login-container {
            flex-direction: column;
          }

          .brand-section {
            padding: 40px 32px;
            min-height: auto;
          }

          .brand-content {
            max-width: 100%;
          }

          .logo-frame {
            width: 100px;
            height: 100px;
          }

          .brand-tagline {
            margin-bottom: 32px;
          }

          .feature-cards {
            display: none;
          }

          .login-section {
            padding: 40px 24px;
            flex: 1;
          }

          .login-card {
            padding: 36px 28px;
          }
        }

        @media (max-width: 480px) {
          .brand-section {
            padding: 32px 24px;
          }

          .logo-frame {
            width: 90px;
            height: 90px;
          }

          .brand-title {
            font-size: 24px;
          }

          .login-card {
            padding: 32px 24px;
            border-radius: var(--radius-lg);
          }

          .login-heading {
            font-size: 22px;
          }
        }
      `}</style>
    </div>
  );
}
