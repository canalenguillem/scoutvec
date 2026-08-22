import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // el proxy evita CORS en desarrollo: el frontend llama a /api/... y Vite
  // lo reenvia a uvicorn
  server: {
    // puerto propio y strictPort: si esta ocupado debe fallar, no derivar a
    // otro numero en silencio y dejarte hablando con la app de al lado
    port: 5180,
    strictPort: true,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true,
                rewrite: p => p.replace(/^\/api/, '') },
    },
  },
})
