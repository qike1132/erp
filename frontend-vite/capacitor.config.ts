import type { CapacitorConfig } from '@capacitor/cli'

const config: CapacitorConfig = {
  appId: 'com.binfa.erp',
  appName: '滨发ERP',
  webDir: 'dist',
  server: {
    androidScheme: 'http',
    hostname: 'localhost',
    allowNavigation: ['192.168.0.95:*'],
  },
  plugins: {
    StatusBar: {
      style: 'LIGHT',
      backgroundColor: '#F5F5F7',
    },
    SplashScreen: {
      backgroundColor: '#F5F5F7',
      showSpinner: true,
      spinnerColor: '#FF9500',
      splashFullScreen: true,
      splashImmersive: true,
      fadeInDuration: 200,
      fadeOutDuration: 200,
    },
    Keyboard: {
      resize: 'body',
      resizeOnFullScreen: true,
    },
    Preferences: {
      group: 'BinfaERP',
    },
  },
  android: {
    buildVariant: 'release',
    allowMixedContent: true,
  },
}

export default config
