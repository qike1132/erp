"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, useRef } from "react";
import {
  ScanLineIcon,
  UploadIcon,
  Loader2Icon,
  FileTextIcon,
  CheckCircleIcon,
  XCircleIcon,
  RefreshCwIcon,
  ImageIcon,
  ArrowRightIcon,
} from "lucide-react";
import { toast } from "sonner";
import Link from "next/link";

// ============ Types ============

interface OcrProgress {
  status: string;
  percent: number;
  message?: string;
}

interface OcrImportResult {
  success: boolean;
  message?: string;
  imported?: number;
  errors?: string[];
  staged_items?: Array<{
    customer?: string;
    product?: string;
    quantity?: number;
    date?: string;
  }>;
}

// ============ Helpers ============

function getCsrfToken(): string | null {
  const match = document.cookie.match(/fastapi_csrf_token=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : null;
}

async function apiFetch<T>(url: string, options: RequestInit = {}): Promise<T> {
  const csrfToken = getCsrfToken();
  const res = await fetch(url, {
    ...options,
    credentials: "include",
    headers: {
      ...options.headers,
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
    },
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(err.detail || "请求失败");
  }
  return res.json();
}

// ============ Content ============

export function OcrImportContent() {
  const [taskId, setTaskId] = useState<string | null>(null);
  const [result, setResult] = useState<OcrImportResult | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const { data: progress } = useQuery({
    queryKey: ["ocr-progress", taskId],
    queryFn: () => apiFetch<OcrProgress>(`/api/v1/ocr-import/progress/${taskId}`),
    enabled: !!taskId && (!result),
    refetchInterval: (q) => {
      const d = q.state.data;
      if (!d) return 800;
      if (d.status === "completed" || d.status === "error") return false;
      return 800;
    },
  });

  const uploadMutation = useMutation({
    mutationFn: async (files: FileList) => {
      const taskResp = await apiFetch<{ task_id: string }>("/api/v1/ocr-import/create-task", {
        method: "POST",
      });
      setTaskId(taskResp.task_id);

      const formData = new FormData();
      Array.from(files).forEach((f) => formData.append("files", f));
      const csrfToken = getCsrfToken();
      const res = await fetch(
        `/api/v1/ocr-import/upload?session_id=${encodeURIComponent(taskResp.task_id)}`,
        {
          method: "POST",
          credentials: "include",
          headers: csrfToken ? { "X-CSRF-Token": csrfToken } : {},
          body: formData,
        }
      );
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: "OCR 识别失败" }));
        throw new Error(err.detail || "OCR 识别失败");
      }
      return res.json() as Promise<OcrImportResult>;
    },
    onSuccess: (data) => {
      setResult(data);
      if (data.success) toast.success(data.message || "OCR 识别完成");
      else toast.error(data.message || "OCR 识别失败");
    },
    onError: (err: Error) => {
      toast.error(err.message);
      setTaskId(null);
    },
  });

  function handleUpload() {
    const files = fileRef.current?.files;
    if (!files || files.length === 0) {
      toast.error("请选择至少一个文件");
      return;
    }
    setResult(null);
    uploadMutation.mutate(files);
  }

  function handleReset() {
    setTaskId(null);
    setResult(null);
    if (fileRef.current) fileRef.current.value = "";
  }

  const isProcessing = uploadMutation.isPending || (!!taskId && !result && progress?.status !== "completed" && progress?.status !== "error");

  return (
    <div className="ocr-page-root">
      {/* Page Header */}
      <div className="page-header-wrapper">
        <h2 className="page-title">
          <ScanLineIcon className="mr-2 inline-block h-5 w-5" />
          OCR 出货单识别导入
        </h2>
        <p className="page-subtitle">上传出货单图片/PDF，离线OCR自动识别并导入暂存区</p>
      </div>

      {/* Main Layout: Left Upload + Right Preview */}
      <div className="supplier-layout row g-5">
        {/* Left: Upload Area */}
        <div className="sidebar-panel-col col-xl-5 col-lg-6">
          <div className="sidebar-panel">
            <div className="card collapse-card">
              <div className="card-header d-flex justify-content-between align-items-center">
                <h6 className="mb-0 fw-bold">
                  <UploadIcon className="mr-2 inline-block h-4 w-4" />
                  上传出货单
                </h6>
                <span className="ocr-badge">离线 OCR · RapidOCR</span>
              </div>
              <div className="card-body">
                <div className="upload-area" onClick={() => fileRef.current?.click()}>
                  <ImageIcon className="h-10 w-10 text-plush-blue-deep mb-2" style={{ opacity: 0.6 }} />
                  <p className="upload-area-title">点击选择文件或拖拽到此处</p>
                  <p className="upload-area-hint">支持 PDF、PNG、JPG、JPEG、BMP、TIFF、WEBP</p>
                  <p className="upload-area-hint">可一次选择多个文件</p>
                  <input
                    ref={fileRef}
                    type="file"
                    multiple
                    accept=".pdf,.png,.jpg,.jpeg,.bmp,.tiff,.webp"
                    disabled={isProcessing}
                    className="ocr-file-input"
                  />
                </div>
                <div className="d-flex gap-2 mt-4">
                  <button
                    className="btn-submit-enhanced btn-primary flex-1"
                    onClick={handleUpload}
                    disabled={isProcessing}
                  >
                    {isProcessing ? (
                      <><Loader2Icon className="mr-2 inline-block h-4 w-4 animate-spin" />识别中...</>
                    ) : (
                      <><ScanLineIcon className="mr-2 inline-block h-4 w-4" />开始识别</>
                    )}
                  </button>
                  {(result || taskId) && (
                    <button className="btn-outline-primary" onClick={handleReset} disabled={uploadMutation.isPending}>
                      <RefreshCwIcon className="mr-1 inline-block h-3.5 w-3.5" />重新开始
                    </button>
                  )}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Progress & Results */}
        <div className="main-content-col col-xl-7 col-lg-6">
          {/* Progress */}
          {isProcessing && progress && (
            <div className="ocr-progress-card mb-4">
              <div className="card-header">
                <h6 className="mb-0 fw-bold">
                  <Loader2Icon className="mr-2 inline-block h-4 w-4 animate-spin" />
                  识别进度
                </h6>
              </div>
              <div className="card-body">
                <div className="d-flex justify-content-between text-sm mb-2">
                  <span className="text-muted">{progress.message || progress.status}</span>
                  <span className="font-semibold">{progress.percent}%</span>
                </div>
                <div className="progress-bar-track">
                  <div className="progress-bar-fill" style={{ width: `${progress.percent}%` }} />
                </div>
              </div>
            </div>
          )}

          {/* Results */}
          {result && (
            <>
              {/* Status Card */}
              <div className={`ocr-result-card mb-4 ${result.success ? "ocr-result-success" : "ocr-result-error"}`}>
                <div className="card-body d-flex align-items-center gap-3">
                  {result.success ? (
                    <CheckCircleIcon className="h-8 w-8 shrink-0" style={{ color: "#28C76F" }} />
                  ) : (
                    <XCircleIcon className="h-8 w-8 shrink-0" style={{ color: "#EA5455" }} />
                  )}
                  <div>
                    <h6 className="mb-1 fw-bold">{result.success ? "识别成功" : "识别失败"}</h6>
                    <p className="mb-0 text-sm text-muted">{result.message}</p>
                  </div>
                  {typeof result.imported === "number" && (
                    <div className="ocr-imported-count ml-auto">
                      <span className="ocr-imported-number">{result.imported}</span>
                      <span className="ocr-imported-label">已暂存</span>
                    </div>
                  )}
                </div>
              </div>

              {/* Staged Items Table */}
              {result.staged_items && result.staged_items.length > 0 && (
                <div className="card main-content-card mb-4">
                  <div className="card-header">
                    <h6 className="mb-0 fw-bold">
                      <FileTextIcon className="mr-2 inline-block h-4 w-4" />
                      暂存明细
                      <span className="pc-badge-pending ml-2">{result.staged_items.length} 条</span>
                    </h6>
                  </div>
                  <div className="card-body p-0">
                    <div className="table-responsive table-scroll-area">
                      <table className="table table-hover mb-0">
                        <thead className="sticky-top">
                          <tr>
                            <th>客户</th>
                            <th>产品</th>
                            <th className="text-right">数量</th>
                            <th>日期</th>
                          </tr>
                        </thead>
                        <tbody>
                          {result.staged_items.slice(0, 20).map((item, i) => (
                            <tr key={i}>
                              <td>{item.customer || "-"}</td>
                              <td>{item.product || "-"}</td>
                              <td className="text-right">{item.quantity ?? "-"}</td>
                              <td>{item.date || "-"}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>
              )}

              {/* Errors */}
              {result.errors && result.errors.length > 0 && (
                <div className="ocr-errors-card mb-4">
                  <div className="card-header">
                    <h6 className="mb-0 fw-bold">
                      <XCircleIcon className="mr-2 inline-block h-4 w-4" style={{ color: "#EA5455" }} />
                      错误详情
                      <span className="pc-badge-pending ml-2">{result.errors.length} 条</span>
                    </h6>
                  </div>
                  <div className="card-body">
                    <ul className="ocr-error-list">
                      {result.errors.map((e, i) => <li key={i}>{e}</li>)}
                    </ul>
                  </div>
                </div>
              )}

              {/* Navigate to Batch */}
              <div className="ocr-nav-card">
                <div className="card-body d-flex align-items-center justify-content-between">
                  <div>
                    <p className="mb-0 text-sm text-muted">识别结果已写入暂存区，请前往批次管理确认后正式入库。</p>
                  </div>
                  <Link href="/batch" className="btn-outline-primary">
                    前往暂存审核 <ArrowRightIcon className="ml-1 inline-block h-3.5 w-3.5" />
                  </Link>
                </div>
              </div>
            </>
          )}

          {!result && !isProcessing && (
            <div className="card main-content-card">
              <div className="card-body text-center py-5">
                <ScanLineIcon className="mx-auto mb-3 h-12 w-12 text-muted" />
                <p className="text-muted mb-0">上传出货单文件后开始OCR识别</p>
                <p className="text-muted mt-1" style={{ fontSize: 13 }}>系统将自动识别出货单中的客户、产品、数量等信息</p>
              </div>
            </div>
          )}
        </div>
      </div>

      <style jsx global>{`
        .ocr-page-root {
          padding: 0;
        }

        /* Shared Plush Cute classes */
        .ocr-page-root .pc-badge-pending { background: linear-gradient(135deg, #87ceeb, #b0e0e6); color: #fff; font-size: 11px; font-weight: 600; padding: 2px 8px; border-radius: 8px; margin-left: 8px; }

        .ocr-badge {
          display: inline-block;
          padding: 3px 10px;
          border-radius: 12px;
          font-size: 11px;
          font-weight: 600;
          background: #eef7fb;
          color: #4a7eb5;
        }

        /* Upload Area */
        .upload-area {
          border: 2px dashed #d0dce6;
          border-radius: 16px;
          padding: 32px 20px;
          text-align: center;
          cursor: pointer;
          background: #fafbfc;
          transition: all 0.2s;
          position: relative;
        }
        .upload-area:hover {
          border-color: #87ceeb;
          background: #f0f8ff;
        }
        .upload-area-title {
          font-weight: 600;
          font-size: 14px;
          color: #5A4A4A;
          margin-bottom: 4px;
        }
        .upload-area-hint {
          font-size: 12px;
          color: #8e99a4;
          margin-bottom: 2px;
        }
        .ocr-file-input {
          position: absolute;
          inset: 0;
          opacity: 0;
          cursor: pointer;
        }

        /* Progress */
        .ocr-progress-card {
          background: #fff;
          border-radius: 16px;
          border: 1px solid #e8ecf0;
          overflow: hidden;
          box-shadow: 0 2px 12px rgba(135, 206, 235, 0.08);
        }
        .ocr-progress-card .card-header {
          padding: 14px 18px;
          border-bottom: 1px solid #e8ecf0;
          background: linear-gradient(135deg, #fafbfc 0%, #f1f5f9 100%);
        }
        .progress-bar-track {
          height: 8px;
          background: #e8ecf0;
          border-radius: 4px;
          overflow: hidden;
        }
        .progress-bar-fill {
          height: 100%;
          background: linear-gradient(90deg, #87ceeb, #4a9cc7);
          border-radius: 4px;
          transition: width 0.3s ease;
        }

        /* Result Cards */
        .ocr-result-card {
          border-radius: 16px;
          overflow: hidden;
          border: 1px solid #e8ecf0;
        }
        .ocr-result-success {
          border-left: 4px solid #28C76F;
          background: #f0fdf4;
        }
        .ocr-result-error {
          border-left: 4px solid #EA5455;
          background: #fef2f2;
        }
        .ocr-imported-count {
          text-align: center;
          padding: 8px 16px;
          background: rgba(135, 206, 235, 0.1);
          border-radius: 12px;
        }
        .ocr-imported-number {
          display: block;
          font-size: 24px;
          font-weight: 800;
          color: #4a9cc7;
          line-height: 1;
        }
        .ocr-imported-label {
          display: block;
          font-size: 11px;
          color: #8e99a4;
          margin-top: 2px;
        }

        /* Errors */
        .ocr-errors-card {
          background: #fff;
          border-radius: 16px;
          border: 1px solid #fde2e2;
          overflow: hidden;
        }
        .ocr-errors-card .card-header {
          padding: 14px 18px;
          border-bottom: 1px solid #fde2e2;
          background: #fef7f7;
        }
        .ocr-error-list {
          list-style: none;
          padding: 0;
          margin: 0;
          max-height: 200px;
          overflow-y: auto;
        }
        .ocr-error-list li {
          padding: 8px 18px;
          font-size: 12px;
          color: #e53935;
          border-bottom: 1px solid #fef2f2;
        }
        .ocr-error-list li:last-child { border-bottom: none; }

        /* Nav Card */
        .ocr-nav-card {
          background: #fff;
          border-radius: 16px;
          border: 1px solid #e8ecf0;
          overflow: hidden;
          box-shadow: 0 2px 12px rgba(135, 206, 235, 0.08);
        }
        .ocr-nav-card .card-body {
          padding: 16px 20px;
        }
      `}</style>
    </div>
  );
}
