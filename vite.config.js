import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// The dashboard calls /api/*; in development Vite forwards that to FastAPI.
// Set CMMCREADY_API when the API is not on the default port.
const api = process.env.CMMCREADY_API || 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': api,
    },
  },
  preview: {
    proxy: {
      '/api': api,
    },
  },
})
