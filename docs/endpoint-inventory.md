# Inventario de endpoints registrados

Este inventario corresponde a los routers que `backend/main.py` registra explícitamente. Los antiguos CRUD genéricos, almacenamiento, generación auxiliar, perfiles y edición de variables de entorno fueron retirados o no se registran.

La misma allowlist se aplica en tiempo de ejecución: fuera de estas rutas públicas sólo se despachan la sesión autenticada y el prefijo CRM protegido centralmente. Una ruta API nueva queda inaccesible hasta clasificarse de forma explícita.

| Método y ruta | Clasificación | Datos/operación |
|---|---|---|
| `GET /health` | Público, sólo lectura | Estado genérico `ok`, sin información interna |
| `POST /api/v1/auth/login` | Público, autenticación | Inicio de sesión con rate limit; crea cookies de sesión/CSRF |
| `GET /api/v1/auth/me` | Administrador | Sesión actual, sin hash de contraseña |
| `POST /api/v1/auth/logout` | Administrador + CSRF | Revoca la sesión actual |
| `GET /api/v1/shop/bootstrap` | Público, sólo lectura | Marca pública, categorías, destacados y puntos públicos |
| `GET /api/v1/shop/products` | Público, sólo lectura | Productos activos y campos públicos |
| `GET /api/v1/shop/products/{slug}` | Público, sólo lectura | Detalle público por slug |
| `POST /api/v1/shop/availability` | Público, sólo lectura lógica | Recalcula precio y disponibilidad; no aparta |
| `POST /api/v1/shop/reservations` | Público, creación | Crea una solicitud con schema estricto, body máximo de 32 KiB y cálculo servidor; requiere rate limit compartido en WAF/proxy antes de producción |
| `POST /api/v1/shop/confirmation` | Token privado en cuerpo JSON | Confirmación mínima; los datos bancarios sólo aparecen en estados activos |
| `POST /api/v1/shop/confirmation/cancel` | Token privado en cuerpo JSON | La clienta cancela su apartado activo; libera piezas, lo marca como no leído en el CRM y no envía correos |
| `GET /api/v1/crm/session` | Administrador | Estado de sesión del panel |
| `GET /api/v1/crm/dashboard` | Administrador | Métricas internas |
| `GET /api/v1/crm/reservations` | Administrador | Listado interno de reservaciones |
| `GET /api/v1/crm/reservations/{reservation_id}` | Administrador | Detalle, historial y notificaciones |
| `POST /api/v1/crm/reservations/{reservation_id}/read` | Administrador + CSRF | Marca como leída |
| `POST /api/v1/crm/reservations/{reservation_id}/status` | Administrador + CSRF | Transición de estado e inventario |
| `POST /api/v1/crm/reservations/{reservation_id}/note` | Administrador + CSRF | Nota interna |
| `POST /api/v1/crm/reservations/{reservation_id}/resend` | Administrador + CSRF | Reintenta avisos operativos; rechaza plantillas que necesitan un enlace privado nuevo |
| `POST /api/v1/crm/reservations/{reservation_id}/rotate-confirmation-token` | Administrador + CSRF | Invalida el enlace anterior, genera y envía uno nuevo; si el proveedor falla devuelve el enlace temporal para recuperación manual |
| `POST /api/v1/crm/reservations/{reservation_id}/revoke-confirmation-token` | Administrador + CSRF | Revoca explícitamente el enlace privado actual |
| `GET /api/v1/crm/reservations-export` | Administrador | Exportación CSV |
| `GET /api/v1/crm/catalog` | Administrador | Catálogo interno con stock |
| `POST /api/v1/crm/products` | Administrador + CSRF | Crea producto |
| `PUT /api/v1/crm/products/{product_id}` | Administrador + CSRF | Edita producto |
| `DELETE /api/v1/crm/products/{product_id}` | Administrador + CSRF | Archiva/elimina según reglas del CRM |
| `POST /api/v1/crm/variants` | Administrador + CSRF | Crea variante |
| `PUT /api/v1/crm/variants/{variant_id}` | Administrador + CSRF | Edita variante |
| `DELETE /api/v1/crm/variants/{variant_id}` | Administrador + CSRF | Elimina variante permitida |
| `POST /api/v1/crm/stock-adjust` | Administrador + CSRF | Ajusta stock y registra movimiento |
| `POST /api/v1/crm/categories` | Administrador + CSRF | Crea categoría |
| `PUT /api/v1/crm/categories/{category_id}` | Administrador + CSRF | Edita categoría |
| `DELETE /api/v1/crm/categories/{category_id}` | Administrador + CSRF | Elimina categoría permitida |
| `GET /api/v1/crm/delivery` | Administrador | Configuración interna de entrega |
| `POST /api/v1/crm/delivery-points` | Administrador + CSRF | Crea punto |
| `PUT /api/v1/crm/delivery-points/{point_id}` | Administrador + CSRF | Edita punto |
| `DELETE /api/v1/crm/delivery-points/{point_id}` | Administrador + CSRF | Elimina punto permitido |
| `POST /api/v1/crm/delivery-slots` | Administrador + CSRF | Crea horario |
| `PUT /api/v1/crm/delivery-slots/{slot_id}` | Administrador + CSRF | Edita horario |
| `DELETE /api/v1/crm/delivery-slots/{slot_id}` | Administrador + CSRF | Elimina horario |
| `GET /api/v1/crm/settings` | Administrador | Configuración pública y privada, incluida CLABE |
| `PUT /api/v1/crm/settings/store` | Administrador + CSRF | Edita configuración pública |
| `PUT /api/v1/crm/settings/private` | Administrador + CSRF | Edita banco, CLABE y destinatarios |

Las dependencias administrativas y CSRF se agregan al router CRM completo en `main.py`; no dependen de que cada función recuerde declararlas. La lista pública comprobable vive en `main.PUBLIC_ENDPOINTS` y una prueba compara esa allowlist con las rutas reales.
