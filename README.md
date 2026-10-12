# Nébula Beauty MX — candidato de publicación

Catálogo y solicitudes de apartado sin cuentas de clienta ni pagos en línea. La API pública expone únicamente catálogo, disponibilidad, creación de apartados, contenido y confirmaciones privadas; el CRM usa sesión administrativa local, cookie `HttpOnly` y CSRF.

## Versiones y instalación reproducible

- Python 3.12.13 (la serie 3.12 es obligatoria para la validación de release).
- Node.js 22 LTS. El `package.json` rechaza versiones fuera de `>=22 <25`.
- pnpm 11.22.0 mediante Corepack.
- PostgreSQL en producción. SQLite sólo se admite para desarrollo y pruebas locales.

Las dependencias directas del backend están fijadas exactamente en `backend/requirements.txt`; `backend/requirements.lock` fija también las transitivas. FastAPI 0.141.1/Starlette 1.6.0 usa HTTPX2 para `TestClient`, por eso el lock incluye `httpx2==2.12.0`; `httpx==0.28.1` se conserva únicamente para el cliente de correo de la aplicación. La suite no debe emitir la advertencia de compatibilidad Starlette/HTTPX.

En PowerShell:

```powershell
Copy-Item .env.example .env
Copy-Item frontend/.env.example frontend/.env

py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r backend/requirements.lock

Set-Location frontend
corepack enable
corepack prepare pnpm@11.22.0 --activate
pnpm install --frozen-lockfile
```

En Linux/macOS, `./start_app_v2.sh --install` hace la instalación equivalente con `python3.12`. El workspace de pnpm conserva `minimumReleaseAge: 1440` y un almacén local; no desactives esa política para regenerar el lock.

## Migraciones

Alembic es la única fuente del esquema. `backend/alembic.ini` deja `sqlalchemy.url` realmente vacío; `alembic/env.py` toma `MIGRATION_DATABASE_URL` cuando está configurada y, en caso contrario, reutiliza el `DATABASE_URL` validado. En producción se recomienda que `MIGRATION_DATABASE_URL` sea el endpoint PostgreSQL directo del proveedor, no el pooler transaccional. Si sólo está disponible el pooler, la configuración compartida desactiva las dos cachés de prepared statements, usa nombres únicos y `NullPool` también para Alembic.

```powershell
Set-Location backend
python -m alembic upgrade head
```

La migración `20260824_01` endurece relaciones, unicidad e inventario. Si encuentra tokens privados crudos en una base heredada se detiene antes de cambiar el esquema. Tras revisar la base, autoriza de forma explícita la invalidación de esos enlaces:

```powershell
$env:ALLOW_LEGACY_TOKEN_INVALIDATION = '1'
python -m alembic upgrade head
Remove-Item Env:ALLOW_LEGACY_TOKEN_INVALIDATION
```

Las reservaciones se conservan, los enlaces antiguos quedan revocados y sólo permanecen hashes SHA-256. `20260825_02` reemplaza únicamente las URLs heredadas conocidas por activos WebP incluidos en `/images`; puede ejecutarse más de una vez sin alterar otros valores.

## Inicialización de producción

El orden operativo es deliberado:

1. Configura `ENVIRONMENT=production`, PostgreSQL en `DATABASE_URL`, `APP_DEBUG=false`, `AUTO_MIGRATE=false`, `LOAD_SEED_DATA=false`, `AUTH_SECRET` aleatorio de al menos 32 caracteres y el mismo origen canónico HTTPS —sin ruta, credenciales ni `/` final— tanto en `PUBLIC_SITE_URL` como en el único valor de `ALLOWED_ORIGINS`. Configura `DATABASE_POOL_MODE=transaction` si el endpoint es un pooler transaccional que no puede detectarse por host o puerto, y prefiere una `MIGRATION_DATABASE_URL` directa.
2. Ejecuta `python -m alembic upgrade head` como paso de release.
3. Ejecuta una sola vez `python -m cli init-catalog`. Es transaccional e idempotente: carga categorías, catálogo, variantes, imágenes, puntos y horarios sólo si todo el conjunto está vacío. No crea administradores, no carga `private_settings` y no contiene una CLABE de demostración.
4. Crea el primer administrador: `python -m cli create-admin --email admin@example.com --name "Administradora"`. La contraseña se solicita sin mostrarla; también puede recibirse por stdin en automatización segura.
5. Inicia la aplicación.
6. En el CRM configura datos bancarios reales y destinatarios de alertas. No los pongas en seeds, repositorio ni variables públicas del frontend.

`./start_app_v2.sh --migrate`, `--init-catalog` y `--create-admin EMAIL [NAME]` ofrecen los mismos pasos por separado. El arranque de producción nunca debe activar la carga automática de seeds.

## Arquitectura same-origin

La arquitectura oficial sirve el build de la SPA y las rutas `/api` bajo el mismo dominio mediante `backend/lambda_handler.py`. En producción `VITE_API_BASE_URL` debe permanecer vacío: las llamadas del navegador usan rutas relativas. El build falla si se configura una base de API no vacía o si se detectan orígenes distintos. El backend también se niega a iniciar si `PUBLIC_SITE_URL` y el único `ALLOWED_ORIGINS` no son exactamente el mismo origen público HTTPS canónico. Backend y frontend restringen los orígenes de producción a nombres DNS y rechazan cualquier IP literal, además de rutas, credenciales, query, fragmentos, puerto `443` explícito y `/` final.

El release debe inyectar el mismo valor fuente en `VITE_PUBLIC_SITE_URL`, `PUBLIC_SITE_URL` y `ALLOWED_ORIGINS`. Cuando las dos variables backend están disponibles durante el build, Vite valida explícitamente las tres y exige igualdad exacta; si el proveedor separa build y runtime, Vite sólo puede validar `VITE_PUBLIC_SITE_URL` y el arranque backend valida las otras dos, por lo que la igualdad cross-stack debe comprobarse en la configuración del release y no se infiere automáticamente. Esto es obligatorio mientras el frontend lea `nebula_csrf` desde `document.cookie`: la cookie CSRF es host-only y legible por JavaScript; la cookie de sesión sigue siendo host-only, `HttpOnly`, `Secure` en producción y `SameSite=Lax`. Ninguna cookie define `Domain`.

Los documentos HTML servidos por Lambda incluyen `Content-Security-Policy: frame-ancestors 'none'` y `X-Frame-Options: DENY`. HSTS debe habilitarse en el edge HTTPS del dominio canónico, donde puede aplicarse únicamente después de verificar que todo el tráfico y los subdominios cubiertos usan TLS.

No se debe separar la SPA y la API en subdominios. Si esa arquitectura cambiara en el futuro, habría que reemplazar primero el mecanismo CSRF y volver a revisar CORS y cookies; ampliar `Domain` no es la solución aprobada.

## Confirmaciones y seguridad operativa

El token privado viaja en el fragmento `/confirmacion#t=TOKEN`; los fragmentos no se envían en la URL HTTP. El frontend lo lee y hace `POST /api/v1/shop/confirmation` con el token en JSON. Tanto la respuesta inicial que entrega el token como las respuestas privadas usan `Cache-Control: no-store`, `Pragma: no-cache`, `Referrer-Policy: no-referrer` y `X-Robots-Tag` restrictivo.

Cada consulta de confirmación bloquea solamente la reservación identificada por el token. Si ya venció, la transición a `vencida`, la liberación de inventario y el historial se persisten atómicamente y son idempotentes. `expires_at` sólo se acepta como datetime completo con separador `T`, segundos y zona `Z` o `±HH:MM`; formatos que Python pudiera interpretar pero no sean canónicos entran en fallo seguro. Si la fecha está ausente o es inválida, la confirmación falla sin datos bancarios ni liberación arbitraria de inventario y agrega una alerta operativa idempotente en las notas internas para que el CRM la marque como pendiente de corrección o cancelación. La nota administrativa conserva su límite de 2,000 caracteres y la alerta del sistema se almacena adicionalmente, sin truncarla; guardados posteriores desde el CRM preservan la alerta. El barrido general aplica la misma regla y registra el incidente. Los estados terminales (`cancelada`, `vencida`, `entregada` y `no_show`) pueden conservar el resumen, pero nunca reciben datos bancarios.

No se agregó una restricción de esquema sobre `expires_at`: la columna histórica es texto nullable y PostgreSQL/SQLite no comparten una validación ISO portable. Convertirla a `NOT NULL` sin conocer el vencimiento correcto destruiría o inventaría datos existentes. La aplicación impide nuevas fechas vacías y pone los registros heredados dañados en fallo seguro; antes de endurecer el esquema se debe corregir o cancelar esos registros y después crear una migración reversible.

El CRM ofrece una acción explícita para generar y enviar un enlace nuevo. La rotación invalida el hash anterior y el correo incluye `/confirmacion#t=TOKEN`. Si el proveedor no confirma el envío, la respuesta puntual entrega el nuevo token al administrador para copiarlo; sólo permanece en memoria de esa pantalla. El reenvío genérico rechaza plantillas activas que requerirían un token no recuperable. Revocar bloquea el enlace actual y los estados terminales no pueden generar enlaces nuevos.

Todos los campos ORM `DateTime(timezone=True)` usan el callable compartido `utc_now()`; las asignaciones manuales de sesión también son UTC consciente. Cuando SQLite devuelve un datetime sin `tzinfo`, se interpreta como UTC. La zona horaria de Ciudad de México se reserva para fechas, horarios de entrega y presentación comercial.

El limitador de login vive en memoria y protege sólo cada instancia del proceso. En un despliegue con varias instancias configura además un rate limit compartido en el balanceador/WAF/plataforma para `/api/v1/auth/login` y monitoriza respuestas 401/429.

Antes de producción también es obligatorio configurar un rate limit compartido en WAF, proxy o balanceador para `POST /api/v1/shop/reservations`. Debe limitar ráfagas y volumen sostenido por señales controladas por infraestructura (por ejemplo IP/origen de red), incluir un techo global y generar métricas/alertas de respuestas 413/422/429. El `fingerprint` enviado por el navegador es sólo una señal almacenable y nunca una identidad confiable ni la única clave del límite. No existe un limitador local en memoria para esta ruta porque no daría protección completa entre instancias.

La API rechaza el body de creación al superar 32 KiB y el schema limita cada apartado a 30 líneas distintas, 20 unidades por variante y 60 unidades totales. Estas validaciones ocurren antes de bloquear filas de inventario; el motor repite los topes como defensa interna antes de ejecutar `SELECT ... FOR UPDATE`.

PostgreSQL es necesario para comprobar el bloqueo real `SELECT ... FOR UPDATE`: antes de publicar ejecuta la suite contra una URL PostgreSQL de staging y confirma que dos solicitudes simultáneas por la última unidad producen exactamente un éxito. SQLite serializa localmente como defensa complementaria, pero no sustituye esa prueba distribuida.

## Verificación

Backend, desde `backend` con el entorno virtual activo:

```powershell
python -m alembic upgrade head
python -m alembic check
python -m pytest tests -q
```

Frontend, desde `frontend`:

```powershell
pnpm install --frozen-lockfile
pnpm lint
pnpm typecheck
pnpm test
$env:VITE_PUBLIC_SITE_URL = 'https://staging.example.com'
$env:VITE_API_BASE_URL = ''
pnpm build
pnpm audit --prod
```

El build copia los WebP de `frontend/public/images` a `frontend/dist/images`. No se requieren servicios de pago, rutas generadas de entidades, almacenamiento o IA.
