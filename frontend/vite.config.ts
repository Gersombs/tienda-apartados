import { defineConfig, loadEnv, type ResolvedConfig } from 'vite';
import react from '@vitejs/plugin-react-swc';
import fs from 'node:fs';
import path from 'path';
import Sitemap from 'vite-plugin-sitemap';
import { validateReleaseOrigins } from './origin-validation.ts';

function escapeHtmlAttr(str: string): string {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

process.env.VITE_APP_TITLE ??= 'Nébula Beauty MX';
process.env.VITE_APP_DESCRIPTION ??= 'Aparta cosméticos y recíbelos en un punto de entrega en Ciudad de México.';
process.env.VITE_APP_TITLE = escapeHtmlAttr(process.env.VITE_APP_TITLE);
process.env.VITE_APP_DESCRIPTION = escapeHtmlAttr(process.env.VITE_APP_DESCRIPTION);
process.env.VITE_APP_LOGO_URL ??= '/favicon.svg';

function ensureBuildOutDir() {
  let outDir = path.resolve(__dirname, 'dist');

  return {
    name: 'ensure-build-out-dir',
    configResolved(config: ResolvedConfig) {
      outDir = path.resolve(config.root, config.build.outDir);
    },
    writeBundle() {
      fs.mkdirSync(outDir, { recursive: true });
    },
  };
}

// https://vitejs.dev/config/
export default defineConfig(({ command, mode }) => {
  const fileEnv = loadEnv(mode, __dirname, '');
  const configuredPublicSiteUrl =
    process.env.VITE_PUBLIC_SITE_URL ||
    fileEnv.VITE_PUBLIC_SITE_URL ||
    'http://localhost:3000';
  const apiBaseUrl = (
    process.env.VITE_API_BASE_URL ??
    fileEnv.VITE_API_BASE_URL ??
    ''
  ).trim().replace(/\/$/, '');
  const productionRelease = command === 'build' && mode === 'production';
  const publicSiteUrl = productionRelease
    ? validateReleaseOrigins(
        configuredPublicSiteUrl,
        process.env.PUBLIC_SITE_URL || fileEnv.PUBLIC_SITE_URL,
        process.env.ALLOWED_ORIGINS || fileEnv.ALLOWED_ORIGINS,
      )
    : configuredPublicSiteUrl.replace(/\/$/, '');
  if (productionRelease && apiBaseUrl) {
    throw new Error(
      'Production uses same-origin API routes: VITE_API_BASE_URL must be empty.',
    );
  }
  if (apiBaseUrl) {
    let frontendOrigin: string;
    let apiOrigin: string;
    try {
      frontendOrigin = new URL(publicSiteUrl).origin;
      apiOrigin = new URL(apiBaseUrl, `${publicSiteUrl}/`).origin;
    } catch {
      throw new Error('VITE_PUBLIC_SITE_URL and VITE_API_BASE_URL must be valid URLs.');
    }
    if (apiOrigin !== frontendOrigin) {
      throw new Error(
        'Frontend and API origins cannot differ while CSRF uses a host-only readable cookie.',
      );
    }
  }
  process.env.VITE_PUBLIC_SITE_URL = publicSiteUrl;
  process.env.VITE_API_BASE_URL = apiBaseUrl;

  return {
    plugins: [
      react(),
      ensureBuildOutDir(),
      Sitemap({
        hostname: publicSiteUrl,
        readable: true,
        generateRobotsTxt: true,
        exclude: ['/admin', '/confirmacion', '/apartado'],
        // Sólo páginas que existen en toda tienda: las categorías cambian según lo que cada una dé de alta.
        dynamicRoutes: [
          '/catalogo',
          '/como-funciona',
          '/preguntas-frecuentes',
          '/politicas-de-apartado',
          '/aviso-de-privacidad',
        ],
        robots: [
          {
            userAgent: '*',
            allow: '/',
            disallow: ['/admin', '/confirmacion', '/apartado'],
          },
        ],
      }),
    ],
    resolve: {
      alias: {
        '@': path.resolve(__dirname, './src'),
      },
    },
    server: {
      host: '0.0.0.0', // Listen on all network interfaces.
      port: parseInt(process.env.VITE_PORT || '3000'),
      proxy: {
        '/api': {
          target: `http://localhost:${process.env.BACKEND_PORT || '8000'}`,
          changeOrigin: true,
        },
      },
      watch: { usePolling: true, interval: 600 },
    },
    build: {
      rollupOptions: {
        output: {
          manualChunks: {
            // Vendor chunks
            'react-vendor': ['react', 'react-dom'],
            'router-vendor': ['react-router-dom'],
            'ui-vendor': [
              '@radix-ui/react-accordion',
              '@radix-ui/react-checkbox',
              '@radix-ui/react-label',
              '@radix-ui/react-select',
              '@radix-ui/react-slot',
              '@radix-ui/react-tabs',
              '@radix-ui/react-toast',
            ],
            'utils-vendor': [
              'clsx',
              'tailwind-merge',
              'class-variance-authority',
              'lucide-react',
            ],
          },
        },
      },
      chunkSizeWarningLimit: 1000,
    },
  };
});
