import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/goals': 'http://localhost:8000',
      '/tasks': 'http://localhost:8000',
      '/insights': 'http://localhost:8000'
    }
  }
})
