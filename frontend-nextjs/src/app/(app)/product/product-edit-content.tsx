"use client";

import { useQuery, useMutation } from "@tanstack/react-query";
import { get, post, put } from "@/lib/api-client";
import { useParams, useRouter } from "next/navigation";
import { useMemo, useState, useRef } from "react";

interface ProductDetail {
  id: number;
  name: string;
  barcode: string;
  price: number;
  image: string | null;
  create_time: string;
  update_time: string;
  status: string;
}

interface ProductFormState {
  name: string;
  barcode: string;
  price: string;
  image: string;
  status: boolean;
}

export function ProductEditContent() {
  const params = useParams();
  const router = useRouter();
  const productId = params.id as string;
  const isEdit = productId !== "new";
  const fileRef = useRef<HTMLInputElement>(null);

  const emptyForm = useMemo<ProductFormState>(() => ({
    name: "", barcode: "", price: "", image: "", status: true,
  }), []);
  const [draft, setDraft] = useState<ProductFormState | null>(null);
  const [uploading, setUploading] = useState(false);
  const [imageModalOpen, setImageModalOpen] = useState(false);

  const { data: productData, isLoading } = useQuery({
    queryKey: ["products", "detail", productId],
    queryFn: () => get<ProductDetail>("/products/" + productId),
    enabled: isEdit,
  });

  const initialForm = useMemo<ProductFormState>(() => {
    if (!productData) return emptyForm;
    return {
      name: productData.name,
      barcode: productData.barcode || "",
      price: productData.price?.toString() || "",
      image: productData.image || "",
      status: productData.status === "active",
    };
  }, [emptyForm, productData]);

  const form = draft ?? initialForm;

  const updateForm = (patch: Partial<ProductFormState>) => {
    setDraft({ ...form, ...patch });
  };

  async function handleImageUpload() {
    const file = fileRef.current?.files?.[0];
    if (!file) return;

    const allowedTypes = ["image/jpeg", "image/jpg", "image/png", "image/gif"];
    if (!allowedTypes.includes(file.type)) { alert("只支持 JPG、PNG、GIF 格式的图片"); return; }
    if (file.size > 2 * 1024 * 1024) { alert("文件大小不能超过 2MB"); return; }

    setUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", file);
      const csrfToken = document.cookie.match(/fastapi_csrf_token=([^;]+)/)?.[1];
      const res = await fetch("/api/v1/auth/upload", {
        method: "POST",
        headers: csrfToken ? { "X-CSRF-Token": decodeURIComponent(csrfToken) } : {},
        credentials: "include",
        body: formData,
      });
      if (!res.ok) throw new Error("上传失败");
      const data = await res.json() as { success: boolean; url: string };
      if (data.success && data.url) {
        updateForm({ image: data.url });
      } else {
        throw new Error("上传返回数据异常");
      }
    } catch (err) {
      alert(err instanceof Error ? err.message : "上传失败");
    } finally {
      setUploading(false);
    }
  }

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = {
        name: form.name,
        barcode: form.barcode || undefined,
        price: form.price ? parseFloat(form.price) : undefined,
        image: form.image || undefined,
        status: form.status ? "active" : "inactive",
      };
      if (isEdit) return put<{ success: boolean; message?: string }>(`/products/edit/${productId}`, body);
      return post<{ success: boolean; message?: string }>("/products/create", body);
    },
    onSuccess: (res) => { alert(res.message || "保存成功"); router.push("/product"); },
    onError: (err: Error) => alert(err.message),
  });

  if (isEdit && isLoading) {
    return (
      <div className="pe-page-root">
        <div className="text-center py-5"><p className="text-muted">加载产品数据...</p></div>
      </div>
    );
  }

  return (
    <div className="pe-page-root">
      <div className="container-fluid">
        <div className="page-header-wrapper">
          <h2 className="page-title">编辑产品</h2>
          <p className="page-subtitle">修改产品信息</p>
        </div>

        <div className="row">
          <div className="col-lg-6">
            <div className="card mt-3">
              <div className="card-header">
                <i className="fas fa-user-edit" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>产品信息
              </div>
              <div className="card-body">
                <form onSubmit={e => { e.preventDefault(); if (form.name) saveMutation.mutate(); }}>
                  <div className="form-group-enhanced">
                    <label htmlFor="name" className="form-label">
                      <i className="fas fa-tag" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>产品名称 <span className="text-danger">*</span>
                    </label>
                    <input type="text" className="form-control" id="name" value={form.name} onChange={e => updateForm({ name: e.target.value })} required placeholder="例如：小熊毛绒玩具" />
                  </div>
                  <div className="form-group-enhanced">
                    <label htmlFor="barcode" className="form-label">
                      <i className="fas fa-barcode" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>69码/商品条码
                    </label>
                    <input type="text" className="form-control" id="barcode" value={form.barcode} onChange={e => updateForm({ barcode: e.target.value })} placeholder="例如：6958085574210" />
                  </div>
                  <div className="form-group-enhanced">
                    <label htmlFor="price" className="form-label">
                      <i className="fas fa-yen-sign" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>产品价格
                    </label>
                    <input type="number" className="form-control" id="price" value={form.price} onChange={e => updateForm({ price: e.target.value })} step="0.01" min="0" placeholder="请输入产品价格" />
                  </div>
                  <div className="form-group-enhanced">
                    <label className="form-label">
                      <i className="fas fa-image" style={{ marginRight: 4, color: "var(--plush-blue-text, #007bff)" }}></i>产品图片
                    </label>
                    <div
                      className="upload-zone"
                      onClick={() => fileRef.current?.click()}
                      onDragOver={e => { e.preventDefault(); (e.currentTarget as HTMLElement).classList.add("dragover"); }}
                      onDragLeave={e => { (e.currentTarget as HTMLElement).classList.remove("dragover"); }}
                      onDrop={e => { e.preventDefault(); (e.currentTarget as HTMLElement).classList.remove("dragover"); const f = e.dataTransfer.files[0]; if (f) { const dt = new DataTransfer(); dt.items.add(f); if (fileRef.current) { fileRef.current.files = dt.files; handleImageUpload(); } } }}
                    >
                      <p>拖拽图片到这里，或者点击选择图片</p>
                      <input ref={fileRef} type="file" style={{ display: "none" }} accept="image/*" onChange={handleImageUpload} />
                      <div className="mt-2">
                        {form.image ? (
                          <img
                            src={form.image}
                            alt="产品图片"
                            className="product-thumbnail"
                            style={{ maxWidth: 250, maxHeight: 250, objectFit: "contain", cursor: "pointer", borderRadius: 4 }}
                            onClick={e => { e.stopPropagation(); setImageModalOpen(true); }}
                          />
                        ) : uploading ? (
                          <p className="text-muted small">上传中...</p>
                        ) : null}
                      </div>
                    </div>
                  </div>
                  <div className="d-flex gap-2 mt-4">
                    <button type="submit" className="btn btn-primary btn-lg" disabled={saveMutation.isPending || uploading}>
                      <i className="fas fa-save" style={{ marginRight: 8 }}></i>{saveMutation.isPending ? "保存中..." : "保存修改"}
                    </button>
                    <a href="/product" className="btn btn-secondary btn-lg" onClick={e => { e.preventDefault(); router.push("/product"); }}>
                      <i className="fas fa-arrow-left" style={{ marginRight: 8 }}></i>返回列表
                    </a>
                  </div>
                </form>
              </div>
            </div>
          </div>

          {isEdit && productData && (
            <div className="col-lg-6">
              <div className="card mt-3">
                <div className="card-header">
                  <i className="fas fa-info-circle" style={{ marginRight: 8, color: "var(--plush-blue-text, #007bff)" }}></i>产品信息
                </div>
                <div className="card-body">
                  <table className="table table-borderless">
                    <tbody>
                      <tr>
                        <td className="text-muted" style={{ width: 120 }}>创建时间</td>
                        <td>{productData.create_time || "-"}</td>
                      </tr>
                      <tr>
                        <td className="text-muted">更新时间</td>
                        <td>{productData.update_time || "-"}</td>
                      </tr>
                    </tbody>
                  </table>
                  <div className="alert-info mt-3">
                    <i className="fas fa-lightbulb" style={{ marginRight: 8 }}></i>
                    <strong>提示：</strong>产品图片支持 JPG、PNG、GIF 格式，文件大小不超过 2MB。
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* Image Modal */}
      {imageModalOpen && form.image && (
        <div className="modal-overlay" onClick={() => setImageModalOpen(false)}>
          <div className="modal-content-elegant" onClick={e => e.stopPropagation()} style={{ maxWidth: 900, width: "90vw" }}>
            <div className="modal-header-elegant">
              <h5 className="modal-title-elegant">产品图片</h5>
              <button className="btn-close-elegant" onClick={() => setImageModalOpen(false)}><i className="fas fa-times"></i></button>
            </div>
            <div className="modal-body-elegant">
              <img src={form.image} className="modal-image-elegant" alt="产品图片" />
            </div>
          </div>
        </div>
      )}

      <style jsx global>{`
        .pe-page-root .container-fluid { padding: 0 16px; }
        .pe-page-root .page-header-wrapper { margin-bottom: 32px; padding-bottom: 24px; border-bottom: 3px solid var(--plush-blue-light, #e0e0e0); }
        .pe-page-root .page-title { color: var(--plush-text, #2d3748); font-size: 24px; font-weight: 400; margin-bottom: 8px; letter-spacing: -0.5px; }
        .pe-page-root .page-subtitle { color: var(--plush-text-light, #718096); font-size: 18px; margin: 0; }
        .pe-page-root .row { display: flex; flex-wrap: wrap; margin: 0 -12px; }
        .pe-page-root .col-lg-6 { flex: 0 0 50%; max-width: 50%; padding: 0 12px; }
        .pe-page-root .card { background: #fff; border: 1px solid rgba(0,0,0,.125); border-radius: .375rem; }
        .pe-page-root .card-header { padding: 24px; background: linear-gradient(135deg, #f8fafc, #fff); border-bottom: 1px solid #f1f5f9; font-weight: 600; }
        .pe-page-root .card-body { padding: 24px; }
        .pe-page-root .mt-3 { margin-top: .75rem; }
        .pe-page-root .form-group-enhanced { margin-bottom: 24px; }
        .pe-page-root .form-label { display: flex; align-items: center; font-weight: 400; color: var(--plush-text, #2d3748); font-size: 14px; margin-bottom: 8px; letter-spacing: 0.2px; }
        .pe-page-root .form-control { padding: 8px 16px; border-radius: 8px; border: 2px solid var(--plush-blue-light, #e0e0e0); font-size: 14px; transition: all 0.3s ease; min-height: 44px; width: 100%; }
        .pe-page-root .form-control:focus { border-color: var(--plush-blue-text, #007bff); box-shadow: 0 0 0 .2rem rgba(135,206,235,0.25); outline: none; }
        .pe-page-root .text-danger { color: #dc3545; }
        .pe-page-root .text-muted { color: #6c757d; }
        .pe-page-root .upload-zone { border: 2px dashed #cbd5e1; border-radius: 16px; padding: 2rem 1.5rem; text-align: center; background: #fff; cursor: pointer; transition: all 0.3s ease; min-height: 100px; }
        .pe-page-root .upload-zone:hover { border-color: #3b82f6; background: linear-gradient(135deg, #eff6ff, #f8fafc); }
        .pe-page-root .upload-zone.dragover { border-color: #3b82f6; background: rgba(59,130,246,0.05); }
        .pe-page-root .d-flex { display: flex; }
        .pe-page-root .gap-2 { gap: .5rem; }
        .pe-page-root .mt-4 { margin-top: 1.5rem; }
        .pe-page-root .btn-lg { padding: 16px 32px; font-size: 16px; border-radius: 16px; min-width: 160px; }
        .pe-page-root .btn-primary { color: #fff; background-color: #0d6efd; border-color: #0d6efd; }
        .pe-page-root .btn-primary:disabled { opacity: .65; cursor: not-allowed; }
        .pe-page-root .btn-secondary { color: #6c757d; background: #fff; border: 2px solid #e2e8f0; }
        .pe-page-root .table-borderless td { padding: 12px 0; border: none; }
        .pe-page-root .alert-info { background: linear-gradient(135deg, rgba(176,224,230,0.2), rgba(212,241,244,0.3)); border: 2px solid var(--plush-blue-light, #e0e0e0); border-radius: 16px; color: var(--plush-text, #2d3748); padding: 16px; font-size: 14px; }

        /* Modal */
        .pe-page-root .modal-overlay { position: fixed; top: 0; left: 0; right: 0; bottom: 0; background: rgba(0,0,0,0.5); z-index: 1050; display: flex; align-items: center; justify-content: center; }
        .pe-page-root .modal-content-elegant { background: #fff; border-radius: 24px; box-shadow: 0 25px 50px -12px rgba(0,0,0,0.25); overflow: hidden; }
        .pe-page-root .modal-header-elegant { padding: 1.5rem 2rem; background: linear-gradient(135deg, #f8fafc, #fff); border-bottom: 1px solid #f1f5f9; display: flex; justify-content: space-between; align-items: center; }
        .pe-page-root .modal-title-elegant { font-size: 1.25rem; font-weight: 600; color: #1e293b; }
        .pe-page-root .btn-close-elegant { width: 40px; height: 40px; border-radius: 10px; border: none; background: #f1f5f9; color: #64748b; display: flex; align-items: center; justify-content: center; font-size: 1.25rem; cursor: pointer; }
        .pe-page-root .btn-close-elegant:hover { background: #e2e8f0; }
        .pe-page-root .modal-body-elegant { padding: 2rem; background: #f8fafc; display: flex; align-items: center; justify-content: center; min-height: 40vh; }
        .pe-page-root .modal-image-elegant { max-width: 100%; max-height: 80vh; object-fit: contain; border-radius: 16px; box-shadow: 0 8px 24px rgba(0,0,0,0.15); }

        @media (max-width: 992px) { .pe-page-root .col-lg-6 { flex: 0 0 100%; max-width: 100%; } }
        @media (max-width: 768px) { .pe-page-root .page-header-wrapper { margin-bottom: 16px; padding-bottom: 16px; } .pe-page-root .page-title { font-size: 20px; } .pe-page-root .d-flex.gap-2 { flex-direction: column; } }
      `}</style>
    </div>
  );
}
