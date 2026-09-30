/**
 * 移动端列表分页常量（S12 数据层统一）。
 *
 * 移动端视图分两类，页大小因此分开定义，避免各视图各写一个魔法数字：
 * - `MOBILE_LIST_PAGE_SIZE`：一次性拉取整表后在**本地**搜索/筛选的视图
 *   （产品、库存）。这些接口没有服务端搜索参数，取大页是为了让本地筛选覆盖全量。
 * - `MOBILE_PAGE_SIZE`：走**服务端分页**的列表视图（采购订单等）。
 */
export const MOBILE_LIST_PAGE_SIZE = 200
export const MOBILE_PAGE_SIZE = 50
