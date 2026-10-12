# Nébula Beauty MX frontend

Vite, React, TypeScript, Tailwind CSS y shadcn/ui. La aplicación usa la API del mismo origen por defecto; el carrito no sensible vive en `localStorage` y la sesión administrativa sólo en cookies del servidor.

```shell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
pnpm build
pnpm dev
```

Usa Node.js 22 LTS y pnpm 11.22.0. Copia `.env.example` a `.env` sólo si necesitas sobrescribir la URL pública o el proxy local. El panel es `/admin`; las confirmaciones usan `/confirmacion#t=TOKEN` y envían el token al backend por POST. Ninguna ruta privada entra al sitemap.
