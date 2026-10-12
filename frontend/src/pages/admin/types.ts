import { useToast } from '@/hooks/use-toast';
import { Reservation } from '@/lib/shop';

/* ----------------------------- Tipos ----------------------------- */
export interface SessionState {
  is_admin: boolean;
  admin_count: number;
  role: string;
  name: string;
}

export interface Dashboard {
  unread_count: number;
  today_count: number;
  upcoming_count: number;
  expired_count: number;
  expected_total: number;
  delivered_total: number;
  delivered_count: number;
  today_deliveries: {
    id: number;
    folio: string;
    customer_name: string;
    delivery_point_name: string;
    slot_start: string;
    slot_end: string;
    total_amount: number;
    status_label: string;
  }[];
  unread: { id: number; folio: string; customer_name: string; total_amount: number; delivery_date: string }[];
  low_stock: {
    variant_id: number;
    product_name: string;
    variant_label: string;
    available_units: number;
    stock: number;
    reserved_stock: number;
  }[];
  activity: {
    id: number;
    folio: string;
    to_status_label: string;
    note: string;
    admin_email: string;
    created_at: string | null;
  }[];
}

export interface StatusOption {
  value: string;
  label: string;
}

export interface ReservationRow {
  id: number;
  folio: string;
  status: string;
  status_label: string;
  customer_name: string;
  customer_whatsapp: string;
  customer_email: string;
  delivery_point_name: string;
  delivery_point_id: number | null;
  delivery_date: string;
  slot_start: string;
  slot_end: string;
  total_amount: number;
  item_count: number;
  is_unread: boolean;
  created_at: string | null;
}

export interface NotificationRow {
  id: number;
  recipient_type: string;
  recipient_email: string;
  template: string;
  status: string;
  error_message: string;
  sent_at: string;
  attempts: number;
}

export interface ReservationDetail {
  reservation: Reservation;
  history: {
    id: number;
    to_status_label: string;
    admin_email: string;
    note: string;
    created_at: string | null;
  }[];
  notifications: NotificationRow[];
  statuses: StatusOption[];
}

export interface VariantRow {
  id: number;
  option_name: string;
  option_value: string;
  label: string;
  sku: string;
  stock: number;
  reserved_stock: number;
  available_units: number;
  price_delta: number;
  is_active: boolean;
}

export interface CatalogProduct {
  id: number;
  name: string;
  slug: string;
  short_description: string;
  full_description: string;
  ingredients: string;
  usage_instructions: string;
  category_id: number | null;
  price: number;
  tags: string;
  is_active: boolean;
  is_featured: boolean;
  is_archived: boolean;
  sort_order: number;
  images: { id: number; url: string; alt_text: string }[];
  variants: VariantRow[];
}

export interface CatalogCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  image_url: string;
  sort_order: number;
  is_active: boolean;
}

export interface CatalogResponse {
  categories: CatalogCategory[];
  products: CatalogProduct[];
}

export interface DeliveryConfig {
  points: {
    id: number;
    name: string;
    kind: string;
    address: string;
    city: string;
    reference: string;
    notes: string;
    sort_order: number;
    is_active: boolean;
  }[];
  slots: {
    id: number;
    delivery_point_id: number;
    weekday: number;
    start_time: string;
    end_time: string;
    capacity: number;
    is_active: boolean;
  }[];
}

export interface SettingsResponse {
  store: Record<string, string | number>;
  private: Record<string, string>;
  email_provider_configured: boolean;
}

export const EMAIL_STATUS_TONE: Record<string, string> = {
  enviado: 'text-emerald-700',
  pendiente: 'text-amber-700',
  fallido: 'text-destructive',
};

export const TEMPLATE_LABELS: Record<string, string> = {
  recibida: 'Solicitud recibida (clienta)',
  confirmada: 'Apartado confirmado (clienta)',
  lista: 'Lista para entregar (clienta)',
  cancelada: 'Cancelación (clienta)',
  vencida: 'Vencimiento (clienta)',
  alerta_negocio: 'Alerta al negocio',
  enlace_privado: 'Enlace privado nuevo',
};

// Botones para mandar un aviso a mano, con lo que hace cada uno.
export const MANUAL_EMAIL_LABELS: Record<string, string> = {
  cancelada: 'A la clienta: su apartado se canceló',
  vencida: 'A la clienta: su apartado venció',
  alerta_negocio: 'A mí: copia del aviso de este apartado',
};

export const LINK_EMAIL_TEMPLATES = new Set(['recibida', 'confirmada', 'lista', 'enlace_privado']);
export const ACTIVE_RESERVATION_STATUSES = new Set(['recibida', 'confirmada', 'preparando', 'lista']);


export type ToastFn = ReturnType<typeof useToast>['toast'];
