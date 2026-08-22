import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
export default defineConfig({
  plugins: [react()],
  build: { ssr: true, minify: false, outDir: '.ssrcheck',
           rollupOptions: { input: 'src/ssr-entry.tsx' } },
})
