import { getAPIBaseURL } from './config';

// El servidor escribe el nombre de cada tienda en el HTML; se usa mientras carga la configuración.
export const SHOP_NAME_FALLBACK =
  document.querySelector('meta[property="og:title"]')?.getAttribute('content') || '';

/* ------------------------------------------------------------------ *
 * Tipos
 * ------------------------------------------------------------------ */
export interface StoreSettings {
  shop_name: string;
  tagline: string;
  logo_url: string;
  hero_image_url: string;
  color_bg: string;
  color_text: string;
  color_accent: string;
  contact_email: string;
  contact_whatsapp: string;
  instagram_url: string;
  tiktok_url: string;
  facebook_url: string;
  how_it_works: string;
  faq_content: string;
  privacy_policy: string;
  reservation_policy: string;
  delivery_instructions: string;
  reservation_window_days: number;
  grace_period_hours: number;
}

export interface Category {
  name: string;
  slug: string;
  description: string;
  image_url: string;
}

export interface ProductCard {
  name: string;
  slug: string;
  short_description: string;
  price: number;
  category_name: string;
  category_slug: string;
  is_featured: boolean;
  tags: string[];
  image_url: string;
  image_alt: string;
  available_units: number;
  availability: string;
}

export interface ProductVariant {
  id: number;
  option_name: string;
  option_value: string;
  label: string;
  price: number;
  available_units: number;
  availability: string;
}

export interface ProductDetail extends ProductCard {
  full_description: string;
  ingredients: string;
  usage_instructions: string;
  images: { url: string; alt_text: string }[];
  variants: ProductVariant[];
}

export interface DeliverySlot {
  id: number;
  start_time: string;
  end_time: string;
  label: string;
  capacity: number;
  remaining: number | null;
}

export interface DeliveryDay {
  date: string;
  weekday_label: string;
  slots: DeliverySlot[];
}

export interface DeliveryPoint {
  id: number;
  name: string;
  kind: string;
  address: string;
  city: string;
  reference: string;
  notes: string;
  days: DeliveryDay[];
}

export interface ReservationItem {
  id?: number;
  product_name: string;
  product_slug: string;
  variant_label: string;
  unit_price: number;
  quantity: number;
  line_total: number;
  image_url: string;
}

export interface Reservation {
  id: number;
  folio: string;
  status: string;
  status_label: string;
  customer_name: string;
  customer_whatsapp: string;
  customer_email: string;
  delivery_point_name: string;
  delivery_point_reference: string;
  delivery_date: string;
  slot_start: string;
  slot_end: string;
  total_amount: number;
  item_count: number;
  customer_notes: string;
  internal_notes: string;
  is_unread: boolean;
  expires_at: string;
  cancel_reason: string;
  created_at: string | null;
  items: ReservationItem[];
}

export interface BankDetails {
  bank_name: string;
  account_holder: string;
  clabe: string;
  account_number: string;
  transfer_instructions: string;
}

/* ------------------------------------------------------------------ *
 * Cliente de API
 * ------------------------------------------------------------------ */
type Method = 'GET' | 'POST' | 'PUT' | 'DELETE';

function csrfToken(): string {
  const raw = document.cookie
    .split('; ')
    .find((entry) => entry.startsWith('nebula_csrf='))
    ?.split('=')
    .slice(1)
    .join('=');
  return raw ? decodeURIComponent(raw) : '';
}

export async function api<T>(
  url: string,
  method: Method = 'GET',
  data: Record<string, unknown> = {},
): Promise<T> {
  const base = getAPIBaseURL().replace(/\/$/, '');
  let target = `${base}${url}`;
  const headers: Record<string, string> = { Accept: 'application/json' };
  const options: RequestInit = { method, credentials: 'include', headers };

  if (method === 'GET') {
    const params = new URLSearchParams();
    Object.entries(data).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
    });
    const query = params.toString();
    if (query) target += `${target.includes('?') ? '&' : '?'}${query}`;
  } else {
    headers['Content-Type'] = 'application/json';
    const csrf = csrfToken();
    if (csrf) headers['X-CSRF-Token'] = csrf;
    options.body = JSON.stringify(data);
  }

  const response = await fetch(target, options);
  const text = await response.text();
  let payload: unknown = null;
  if (text) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = { detail: 'El servidor devolvió una respuesta no válida.' };
    }
  }
  if (!response.ok) {
    if (response.status === 401 && url.startsWith('/api/v1/crm')) {
      window.dispatchEvent(new Event('admin-session-expired'));
    }
    // Los rechazos de validación (422) traen una lista, no un texto: dibujarla tumbaría la página.
    const raw = (payload as { detail?: unknown } | null)?.detail;
    const detail =
      typeof raw === 'string' && raw
        ? raw
        : response.status === 422
          ? 'Revisa tus datos: alguno no es válido (por ejemplo, el correo).'
          : `Error ${response.status}`;
    throw Object.assign(new Error(detail), { data: payload, status: response.status });
  }
  return payload as T;
}

export async function downloadApi(
  url: string,
  data: Record<string, unknown> = {},
): Promise<Response> {
  const base = getAPIBaseURL().replace(/\/$/, '');
  const params = new URLSearchParams();
  Object.entries(data).forEach(([key, value]) => {
    if (value !== undefined && value !== null && value !== '') params.set(key, String(value));
  });
  const query = params.toString();
  const response = await fetch(`${base}${url}${query ? `?${query}` : ''}`, {
    method: 'GET',
    credentials: 'include',
    headers: { Accept: 'text/csv' },
  });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const payload = (await response.json()) as { detail?: string };
      detail = payload.detail || detail;
    } catch {
      // Keep the generic status when the server did not return JSON.
    }
    throw Object.assign(new Error(detail), { status: response.status });
  }
  return response;
}

const MAX_IMAGE_SIDE = 1600;

/** Reduce la foto en el navegador: las fotos de celular pesan varios MB. */
async function shrinkImage(file: File): Promise<Blob> {
  const bitmap = await createImageBitmap(file).catch(() => null);
  if (!bitmap) throw new Error('No pudimos leer esa foto. Prueba con una foto JPG o PNG.');
  const scale = Math.min(1, MAX_IMAGE_SIDE / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement('canvas');
  canvas.width = Math.round(bitmap.width * scale);
  canvas.height = Math.round(bitmap.height * scale);
  const context = canvas.getContext('2d');
  if (!context) throw new Error('Tu navegador no pudo procesar la foto.');
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();

  const encode = (type: string, quality: number) =>
    new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, type, quality));
  const webp = await encode('image/webp', 0.82);
  if (webp && webp.type === 'image/webp') return webp;
  // Safari no codifica WebP: JPEG con fondo blanco para no ennegrecer transparencias.
  context.globalCompositeOperation = 'destination-over';
  context.fillStyle = '#ffffff';
  context.fillRect(0, 0, canvas.width, canvas.height);
  const jpeg = await encode('image/jpeg', 0.85);
  if (!jpeg) throw new Error('Tu navegador no pudo procesar la foto.');
  return jpeg;
}

/** Sube una foto desde el CRM y devuelve su URL pública. */
export async function uploadImage(file: File): Promise<string> {
  const blob = await shrinkImage(file);
  const base = getAPIBaseURL().replace(/\/$/, '');
  const response = await fetch(`${base}/api/v1/crm/uploads`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': blob.type, 'X-CSRF-Token': csrfToken() },
    body: blob,
  });
  const payload = (await response.json().catch(() => null)) as { url?: string; detail?: string } | null;
  if (!response.ok || !payload?.url) {
    if (response.status === 401) window.dispatchEvent(new Event('admin-session-expired'));
    throw new Error(payload?.detail || `Error ${response.status} al subir la foto`);
  }
  return payload.url;
}

export function apiError(error: unknown, fallback = 'Algo salió mal. Intenta de nuevo.'): string {
  const err = error as {
    data?: { detail?: string };
    status?: number;
    message?: string;
  };
  const detail = err?.data?.detail;
  return (typeof detail === 'string' && detail) || err?.message || fallback;
}

/* ------------------------------------------------------------------ *
 * Formato
 * ------------------------------------------------------------------ */
export function pesos(value: number): string {
  return `$${Math.round(Number(value) || 0).toLocaleString('es-MX')}`;
}

export const MESES = [
  'enero',
  'febrero',
  'marzo',
  'abril',
  'mayo',
  'junio',
  'julio',
  'agosto',
  'septiembre',
  'octubre',
  'noviembre',
  'diciembre',
];

const DIAS = ['domingo', 'lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado'];

export function fechaLarga(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  const date = new Date(y, m - 1, d);
  return `${DIAS[date.getDay()]} ${d} de ${MESES[m - 1]}`;
}

export function fechaCorta(iso: string): string {
  if (!iso) return '';
  const [y, m, d] = iso.split('-').map(Number);
  if (!y || !m || !d) return iso;
  return `${String(d).padStart(2, '0')}/${String(m).padStart(2, '0')}/${y}`;
}

export function fechaHora(iso: string | null): string {
  if (!iso) return '';
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleString('es-MX', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export const WEEKDAY_NAMES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

export const AVISO_SIN_PAGO =
  'No pagarás nada en este sitio. La transferencia se realiza al momento de recibir tus productos.';

export function whatsappLink(numero: string, mensaje = ''): string {
  const digits = (numero || '').replace(/\D/g, '');
  const base = `https://wa.me/52${digits}`;
  return mensaje ? `${base}?text=${encodeURIComponent(mensaje)}` : base;
}

/* ------------------------------------------------------------------ *
 * Estado de "Mi apartado" persistido en el navegador
 * ------------------------------------------------------------------ */
export interface CartLine {
  variantId: number;
  slug: string;
  name: string;
  variantLabel: string;
  unitPrice: number;
  quantity: number;
  imageUrl: string;
  maxUnits: number;
}

const CART_KEY = 'nebula.apartado.v1';
const listeners = new Set<(lines: CartLine[]) => void>();

function readCart(): CartLine[] {
  try {
    const raw = localStorage.getItem(CART_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    return parsed.filter(
      (line) => line && typeof line.variantId === 'number' && typeof line.quantity === 'number',
    );
  } catch {
    return [];
  }
}

function writeCart(lines: CartLine[]) {
  try {
    localStorage.setItem(CART_KEY, JSON.stringify(lines));
  } catch {
    /* almacenamiento no disponible */
  }
  listeners.forEach((listener) => listener(lines));
}

export const cart = {
  read: readCart,
  subscribe(listener: (lines: CartLine[]) => void) {
    listeners.add(listener);
    return () => listeners.delete(listener);
  },
  add(line: Omit<CartLine, 'quantity'>, quantity = 1): { ok: boolean; message?: string } {
    const lines = readCart();
    const existing = lines.find((l) => l.variantId === line.variantId);
    const currentQty = existing ? existing.quantity : 0;
    const target = currentQty + quantity;
    if (line.maxUnits <= 0) {
      return { ok: false, message: 'Este producto está agotado.' };
    }
    if (target > line.maxUnits) {
      return { ok: false, message: `Solo quedan ${line.maxUnits} piezas disponibles.` };
    }
    if (existing) {
      existing.quantity = target;
      existing.unitPrice = line.unitPrice;
      existing.maxUnits = line.maxUnits;
    } else {
      lines.push({ ...line, quantity });
    }
    writeCart(lines);
    return { ok: true };
  },
  setQuantity(variantId: number, quantity: number) {
    const lines = readCart();
    const line = lines.find((l) => l.variantId === variantId);
    if (!line) return;
    if (quantity <= 0) {
      writeCart(lines.filter((l) => l.variantId !== variantId));
      return;
    }
    line.quantity = Math.min(quantity, Math.max(1, line.maxUnits));
    writeCart(lines);
  },
  remove(variantId: number) {
    writeCart(readCart().filter((l) => l.variantId !== variantId));
  },
  clear() {
    writeCart([]);
  },
  applyAvailability(
    updates: { variant_id: number; available_units?: number; unit_price?: number; ok: boolean }[],
  ) {
    const lines = readCart();
    const next: CartLine[] = [];
    for (const line of lines) {
      const update = updates.find((u) => u.variant_id === line.variantId);
      if (!update) {
        next.push(line);
        continue;
      }
      // Sin piezas en la respuesta = el producto se desactivó o se borró.
      if (!update.ok && typeof update.available_units !== 'number') continue;
      const max = typeof update.available_units === 'number' ? update.available_units : line.maxUnits;
      if (max <= 0) continue;
      next.push({
        ...line,
        maxUnits: max,
        quantity: Math.min(line.quantity, max),
        unitPrice: typeof update.unit_price === 'number' ? update.unit_price : line.unitPrice,
      });
    }
    writeCart(next);
    return next;
  },
};

export function cartTotals(lines: CartLine[]) {
  const count = lines.reduce((sum, l) => sum + l.quantity, 0);
  const total = lines.reduce((sum, l) => sum + l.unitPrice * l.quantity, 0);
  return { count, total };
}

/* ------------------------------------------------------------------ *
 * Metadatos y noindex
 * ------------------------------------------------------------------ */
function upsertMeta(attr: 'name' | 'property', key: string, content: string) {
  let tag = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${key}"]`);
  if (!tag) {
    tag = document.createElement('meta');
    tag.setAttribute(attr, key);
    document.head.appendChild(tag);
  }
  tag.setAttribute('content', content);
}

export function setSeo(options: {
  title: string;
  description?: string;
  image?: string;
  noindex?: boolean;
}) {
  document.title = options.title;
  if (options.description) {
    upsertMeta('name', 'description', options.description);
    upsertMeta('property', 'og:description', options.description);
  }
  upsertMeta('property', 'og:title', options.title);
  upsertMeta('property', 'og:type', 'website');
  upsertMeta('name', 'twitter:card', 'summary_large_image');
  upsertMeta('name', 'twitter:title', options.title);
  if (options.description) upsertMeta('name', 'twitter:description', options.description);
  if (options.image) {
    upsertMeta('property', 'og:image', options.image);
    upsertMeta('name', 'twitter:image', options.image);
  }
  upsertMeta('name', 'robots', options.noindex ? 'noindex,nofollow' : 'index,follow');
  let canonical = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
  if (options.noindex) {
    canonical?.remove();
  } else {
    if (!canonical) {
      canonical = document.createElement('link');
      canonical.rel = 'canonical';
      document.head.appendChild(canonical);
    }
    canonical.href = `${window.location.origin}${window.location.pathname}`;
  }
}

export function setProductJsonLd(product: ProductDetail | null) {
  const existing = document.getElementById('producto-jsonld');
  if (existing) existing.remove();
  if (!product) return;
  const script = document.createElement('script');
  script.id = 'producto-jsonld';
  script.type = 'application/ld+json';
  script.textContent = JSON.stringify({
    '@context': 'https://schema.org',
    '@type': 'Product',
    name: product.name,
    description: product.short_description,
    image: product.images.map((i) => i.url),
    category: product.category_name,
    offers: {
      '@type': 'Offer',
      price: product.price,
      priceCurrency: 'MXN',
      availability:
        product.available_units > 0
          ? 'https://schema.org/InStock'
          : 'https://schema.org/OutOfStock',
      availableDeliveryMethod: 'https://schema.org/InStorePickup',
    },
  });
  document.head.appendChild(script);
}
