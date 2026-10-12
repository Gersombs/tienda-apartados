# Una imagen por tienda: la URL pública se fija al compilar el frontend.
FROM node:22-slim AS frontend
WORKDIR /app/frontend
RUN corepack enable && corepack prepare pnpm@11.22.0 --activate
COPY frontend/package.json frontend/pnpm-lock.yaml frontend/pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
# Las tres deben ser el mismo origen HTTPS de la tienda; el build falla si no.
ARG VITE_PUBLIC_SITE_URL
ARG PUBLIC_SITE_URL
ARG ALLOWED_ORIGINS
ENV VITE_API_BASE_URL=""
RUN test -n "$VITE_PUBLIC_SITE_URL" || { echo "Falta la variable VITE_PUBLIC_SITE_URL en el servicio (https://dominio-de-la-tienda)."; exit 1; } \
 && pnpm build

FROM python:3.12-slim
WORKDIR /app/backend
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ENVIRONMENT=production \
    AUTO_MIGRATE=false \
    LOAD_SEED_DATA=false \
    DISABLE_FILE_LOGS=1
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ ./
COPY --from=frontend /app/frontend/dist /app/frontend/dist
EXPOSE 8000
# Una sola instancia por tienda, así que migrar al arrancar es seguro.
# shortcut: --forwarded-allow-ips='*' confía en el proxy de la plataforma para la IP real
# del limitador de login; sólo es correcto si el contenedor no es accesible directamente.
CMD ["sh", "-c", "python -m alembic upgrade head && exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
