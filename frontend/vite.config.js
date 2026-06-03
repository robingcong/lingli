import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '^/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '^/core': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '^/upload': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '^/analyser': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '^/api_case_generate': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      },
      '^/download_file': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true
      }
    }
  }
});
