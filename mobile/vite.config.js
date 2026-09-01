import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// This app lives at <repo-root>/mobile inside the purchase_mobile repo, as
// a sibling of the purchase_mobile python module folder (single level,
// matching the working timesheet_kiosk app's layout exactly). The build
// output goes straight into purchase_mobile/www/purchase-app, which
// Frappe's website engine serves automatically at
// https://<your-site>/purchase-app once this app is installed on the site.
export default defineConfig({
  plugins: [react()],
  base: '/purchase-app/',
  build: {
    outDir: '../purchase_mobile/www/purchase-app',
    emptyOutDir: true,
  },
})
