/**
 * 移动端列表分页常量（S12 数据层统一）。
 *
 * 移动端视图分两类，页大小因此分开定义，避免各视图各写一个魔法数字：
 * - `MOBILE_LIST_PAGE_SIZE`：一次拉大页的视图（产品、库存）。2026-10-17 审计
 *   F-FE-MOBILE-07 起产品/库存已改走服务端搜索（/products/list?search、
 *   /stock/inventory?product），本页大小仅作首屏容量，不再依赖本地过滤覆盖全量。
 * - `MOBILE_PAGE_SIZE`：走**服务端分页**的列表视图（采购订单等）。
 */
export const MOBILE_LIST_PAGE_SIZE = 200
export const MOBILE_PAGE_SIZE = 50
