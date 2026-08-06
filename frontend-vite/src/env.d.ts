/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<object, object, any>
  export default component
}

// @capacitor-community/secure-storage 类型声明（可选依赖，仅 Capacitor 环境使用）
declare module '@capacitor-community/secure-storage' {
  export interface SecureStorageGetOptions { key: string }
  export interface SecureStorageSetOptions { key: string; value: string }
  export interface SecureStorageGetResult { value: string }
  export interface SecureStoragePluginInterface {
    get(options: SecureStorageGetOptions): Promise<SecureStorageGetResult>
    set(options: SecureStorageSetOptions): Promise<void>
    remove(options: SecureStorageGetOptions): Promise<void>
    clear(): Promise<void>
    keys(): Promise<{ keys: string[] }>
    getStorageName(): Promise<{ storageName: string }>
    setStorageName(options: { storageName: string }): Promise<void>
  }
  export const SecureStoragePlugin: SecureStoragePluginInterface
}
