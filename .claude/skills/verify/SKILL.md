---
name: verify
description: Levantar la tienda en local con datos de ejemplo y probarla en el navegador y por HTTP.
---

# Verificar la tienda en local (Windows, Git Bash)

1. Build del frontend (desde `frontend/`):
   `VITE_PUBLIC_SITE_URL=https://tienda-apartados-production.up.railway.app pnpm build`
2. Servidor (desde `backend/`, en segundo plano). Usa rutas `C:/...` en `DATABASE_URL`; `/c/...` no abre SQLite:
   `ENVIRONMENT=dev AUTO_MIGRATE=true LOAD_SEED_DATA=true DATABASE_URL="sqlite+aiosqlite:///C:/<scratchpad>/verify.db" AUTH_SECRET=preview-secret-preview-secret-preview-123 PUBLIC_SITE_URL=http://localhost:8765 ALLOWED_ORIGINS=http://localhost:8765 RESEND_API_KEY= PYTHONUTF8=1 ../.venv/Scripts/python.exe -m uvicorn main:app --port 8765`
   `RESEND_API_KEY=` vacío: los correos quedan "pendiente" y no sale ninguno real.
3. Admin de prueba sólo para esa base (contraseña generada en un archivo del scratchpad, nunca en el chat):
   `... python -m cli create-admin --email verifica@example.com --name Verifica --password-stdin < admin-pass.txt` con el mismo `DATABASE_URL`.
4. API del panel con curl: login en `/api/v1/auth/login` con `-H "Origin: http://localhost:8765"`, guarda cookies con `-c`, y manda `X-CSRF-Token` = cookie `nebula_csrf`.
5. Detener: PowerShell `Get-NetTCPConnection -LocalPort 8765 -State Listen | % { Stop-Process -Id $_.OwningProcess -Force }`.

## Trampas

- Texto con acentos (ñ, é) en la línea de comandos de Git Bash llega roto: escribe el JSON a un archivo UTF-8 y usa `--data-binary @archivo`.
- Al leer JSON con Python en Windows usa siempre `PYTHONUTF8=1`; sin eso, guardar de vuelta corrompe "Nébula" en "NÃ©bula".
- En la pestaña automatizada, `scrollIntoView` suave no se mueve (pestaña oculta); el instantáneo sí.
- Para probar subidas lentas de fotos: envuelve `window.fetch` para retrasar `/crm/uploads` y dispara `change` en `#p-fotos` con un `DataTransfer`.
