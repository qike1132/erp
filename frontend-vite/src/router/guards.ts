/**
 * 全局路由守卫注册（集中在一处，便于锁定执行顺序）。
 *
 * vue-router 的 beforeEach 按注册顺序串行执行，先后顺序会改变行为：
 * 认证守卫（resolveNavAccess）内部会触发 authStore.init()，init() 在用户信息就绪后
 * **立即发起** /dashboard/nav-sections（fire-and-forget，不 await）。若「取消上一路由
 * 未完成请求」的守卫排在它后面，就会把本次导航刚发起的导航数据请求一并 abort，
 * 导航数据永远填不上 → 侧边栏空白（2026-10-22 生产事故）。
 * 因此 abortPendingRequests 必须注册在认证守卫之前。
 */
import type { Router } from 'vue-router'
import { abortPendingRequests } from '@/api/request'
import { resolveNavAccess, type NavAccessStore } from './navAccess'

export function installNavigationGuards(router: Router, getStore: () => NavAccessStore): void {
  // 顺序敏感：取消旧请求必须排在认证守卫之前（原因见文件头注释）。
  router.beforeEach(() => {
    abortPendingRequests()
    return true
  })
  router.beforeEach((to) => resolveNavAccess(to, getStore()))
}
