import type { CapacitorConfig } from '@capacitor/cli';

const config: CapacitorConfig = {
  appId: 'com.streamsense.meetflow',
  appName: 'MeetFlow',
  webDir: 'dist',
  server: {
    cleartext: true
  }
};

export default config;
