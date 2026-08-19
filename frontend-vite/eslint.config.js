import js from '@eslint/js'
import tseslint from 'typescript-eslint'
import pluginVue from 'eslint-plugin-vue'
import globals from 'globals'

// Auto-imported globals from unplugin-auto-import
const autoImportGlobals = {
  // vue
  computed: 'readonly', createApp: 'readonly', customRef: 'readonly',
  defineAsyncComponent: 'readonly', defineComponent: 'readonly', effectScope: 'readonly',
  getCurrentInstance: 'readonly', getCurrentScope: 'readonly', h: 'readonly',
  inject: 'readonly', isProxy: 'readonly', isReactive: 'readonly', isReadonly: 'readonly',
  isRef: 'readonly', markRaw: 'readonly', nextTick: 'readonly', onActivated: 'readonly',
  onBeforeMount: 'readonly', onBeforeUnmount: 'readonly', onBeforeUpdate: 'readonly',
  onDeactivated: 'readonly', onErrorCaptured: 'readonly', onMounted: 'readonly',
  onRenderTracked: 'readonly', onRenderTriggered: 'readonly', onScopeDispose: 'readonly',
  onServerPrefetch: 'readonly', onUnmounted: 'readonly', onUpdated: 'readonly',
  provide: 'readonly', reactive: 'readonly', readonly: 'readonly', ref: 'readonly',
  resolveComponent: 'readonly', shallowReactive: 'readonly', shallowReadonly: 'readonly',
  shallowRef: 'readonly', toRaw: 'readonly', toRef: 'readonly', toRefs: 'readonly',
  toValue: 'readonly', triggerRef: 'readonly', unref: 'readonly', useAttrs: 'readonly',
  useCssModule: 'readonly', useCssVars: 'readonly', useId: 'readonly', useModel: 'readonly',
  useSlots: 'readonly', useTemplateRef: 'readonly', watch: 'readonly', watchEffect: 'readonly',
  watchPostEffect: 'readonly', watchSyncEffect: 'readonly',
  // pinia
  acceptHMRUpdate: 'readonly', createPinia: 'readonly', defineStore: 'readonly',
  getActivePinia: 'readonly', mapActions: 'readonly', mapGetters: 'readonly',
  mapState: 'readonly', mapStores: 'readonly', mapWritableState: 'readonly',
  setActivePinia: 'readonly', setMapStoreSuffix: 'readonly', storeToRefs: 'readonly',
  // vue-router
  onBeforeRouteLeave: 'readonly', onBeforeRouteUpdate: 'readonly',
  useLink: 'readonly', useRoute: 'readonly', useRouter: 'readonly',
}

export default tseslint.config(
  js.configs.recommended,
  ...tseslint.configs.recommended,
  ...pluginVue.configs['flat/recommended'],
  {
    languageOptions: {
      globals: {
        ...globals.browser,
        ...autoImportGlobals,
      },
    },
  },
  {
    files: ['**/*.vue'],
    languageOptions: {
      parserOptions: {
        parser: tseslint.parser,
      },
      globals: {
        ...autoImportGlobals,
      },
    },
  },
  {
    rules: {
      '@typescript-eslint/no-explicit-any': 'warn',
      '@typescript-eslint/no-unused-vars': ['warn', { argsIgnorePattern: '^_' }],
      '@typescript-eslint/no-unused-expressions': 'off',
      'no-console': ['error', { allow: ['warn', 'error'] }],
      'vue/multi-word-component-names': 'off',
      'vue/max-attributes-per-line': 'off',
      'vue/singleline-html-element-content-newline': 'off',
      'vue/multiline-html-element-content-newline': 'off',
      'vue/first-attribute-linebreak': 'off',
      'vue/html-self-closing': ['warn', { html: { void: 'always', normal: 'always', component: 'always' } }],
    },
  },
  {
    files: ['src/utils/devLog.ts'],
    rules: {
      'no-console': 'off',
    },
  },
  {
    ignores: ['dist/**', 'node_modules/**', 'src/auto-imports.d.ts', 'src/components.d.ts', 'src/env.d.ts'],
  },
)
