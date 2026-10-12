import { type FormEvent, useCallback, useEffect, useMemo, useState } from 'react';
import {
  AlertTriangle,
  BadgeCheck,
  Boxes,
  CalendarDays,
  Copy,
  Download,
  ImagePlus,
  Link2,
  Loader2,
  LogOut,
  Mail,
  MapPin,
  RefreshCw,
  Search,
  Settings as SettingsIcon,
  ShieldCheck,
  Unlink,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useToast } from '@/hooks/use-toast';
import {
  Reservation,
  WEEKDAY_NAMES,
  api,
  apiError,
  downloadApi,
  fechaCorta,
  fechaHora,
  pesos,
  setSeo,
  uploadImage,
} from '@/lib/shop';

/* ----------------------------- Tipos ----------------------------- */
interface SessionState {
  is_admin: boolean;
  admin_count: number;
  role: string;
  name: string;
}

interface Dashboard {
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

interface StatusOption {
  value: string;
  label: string;
}

interface ReservationRow {
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

interface NotificationRow {
  id: number;
  recipient_type: string;
  recipient_email: string;
  template: string;
  status: string;
  error_message: string;
  sent_at: string;
  attempts: number;
}

interface ReservationDetail {
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

interface VariantRow {
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

interface CatalogProduct {
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

interface CatalogCategory {
  id: number;
  name: string;
  slug: string;
  description: string;
  image_url: string;
  sort_order: number;
  is_active: boolean;
}

interface CatalogResponse {
  categories: CatalogCategory[];
  products: CatalogProduct[];
}

interface DeliveryConfig {
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

interface SettingsResponse {
  store: Record<string, string | number>;
  private: Record<string, string>;
  email_provider_configured: boolean;
}

const EMAIL_STATUS_TONE: Record<string, string> = {
  enviado: 'text-emerald-700',
  pendiente: 'text-amber-700',
  fallido: 'text-destructive',
};

const TEMPLATE_LABELS: Record<string, string> = {
  recibida: 'Solicitud recibida (clienta)',
  confirmada: 'Apartado confirmado (clienta)',
  lista: 'Lista para entregar (clienta)',
  cancelada: 'Cancelación (clienta)',
  vencida: 'Vencimiento (clienta)',
  alerta_negocio: 'Alerta al negocio',
  enlace_privado: 'Enlace privado nuevo',
};

const LINK_EMAIL_TEMPLATES = new Set(['recibida', 'confirmada', 'lista', 'enlace_privado']);
const ACTIVE_RESERVATION_STATUSES = new Set(['recibida', 'confirmada', 'preparando', 'lista']);

/* --------------------------- Componente --------------------------- */
export default function Admin() {
  const { toast } = useToast();
  const [checking, setChecking] = useState(true);
  const [authed, setAuthed] = useState(false);
  const [session, setSession] = useState<SessionState | null>(null);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loggingIn, setLoggingIn] = useState(false);

  useEffect(() => {
    setSeo({
      title: 'Panel administrativo',
      description: 'Panel interno de gestión de reservaciones.',
      noindex: true,
    });
  }, []);

  useEffect(() => {
    const check = async () => {
      try {
        await api('/api/v1/auth/me');
        setAuthed(true);
        const state = await api<SessionState>('/api/v1/crm/session');
        setSession(state);
      } catch {
        setAuthed(false);
      } finally {
        setChecking(false);
      }
    };
    check();
    const expired = () => {
      setAuthed(false);
      setSession(null);
      toast({ title: 'Tu sesión expiró. Inicia sesión de nuevo.', variant: 'destructive' });
    };
    window.addEventListener('admin-session-expired', expired);
    return () => window.removeEventListener('admin-session-expired', expired);
  }, [toast]);

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    setLoggingIn(true);
    try {
      await api('/api/v1/auth/login', 'POST', { email, password });
      const state = await api<SessionState>('/api/v1/crm/session');
      setAuthed(true);
      setSession(state);
      setPassword('');
    } catch (e) {
      toast({ title: apiError(e, 'No pudimos iniciar sesión.'), variant: 'destructive' });
    } finally {
      setLoggingIn(false);
    }
  };

  if (checking) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md items-center justify-center px-4">
        <Loader2 className="h-6 w-6 animate-spin text-primary" />
      </div>
    );
  }

  if (!authed) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
        <form className="rounded-2xl border border-border bg-card p-6" onSubmit={handleLogin}>
          <ShieldCheck className="h-8 w-8 text-primary" />
          <h1 className="mt-3 text-2xl">Panel administrativo</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            Este panel es solo para el equipo de la tienda. Inicia sesión con tu cuenta autorizada para
            continuar.
          </p>
          <div className="mt-5 space-y-4">
            <div>
              <Label htmlFor="admin-email">Correo</Label>
              <Input
                id="admin-email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="admin-password">Contraseña</Label>
              <Input
                id="admin-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
              />
            </div>
          </div>
          <Button className="tap mt-5 w-full rounded-full" type="submit" disabled={loggingIn}>
            {loggingIn ? 'Iniciando…' : 'Iniciar sesión'}
          </Button>
        </form>
      </div>
    );
  }

  if (session && !session.is_admin) {
    return (
      <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
        <div className="rounded-2xl border border-border bg-card p-6">
          <AlertTriangle className="h-8 w-8 text-primary" />
          <h1 className="mt-3 text-2xl">Sin acceso al panel</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            La cuenta está inactiva. Restablécela con el comando administrativo local.
          </p>
        </div>
      </div>
    );
  }

  return <AdminPanel session={session} />;
}

/* ---------------------------- Panel CRM --------------------------- */
function AdminPanel({ session }: { session: SessionState | null }) {
  const { toast } = useToast();
  const [tab, setTab] = useState('dashboard');
  const logout = async () => {
    try {
      await api('/api/v1/auth/logout', 'POST');
    } finally {
      window.location.assign('/admin');
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex w-full max-w-screen-xl items-center gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">CRM</p>
            <h1 className="truncate text-lg">Nébula Beauty MX</h1>
          </div>
          <div className="ml-auto flex items-center gap-2">
            {session?.name ? (
              <span className="hidden text-sm text-muted-foreground sm:inline">{session.name}</span>
            ) : null}
            <Button
              variant="outline"
              size="sm"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
              onClick={logout}
            >
              <LogOut className="mr-1 h-4 w-4" /> Salir
            </Button>
          </div>
        </div>
      </header>

      <div className="mx-auto w-full max-w-screen-xl px-4 py-5">
        <Tabs value={tab} onValueChange={setTab}>
          <TabsList className="grid w-full grid-cols-4">
            <TabsTrigger value="dashboard" className="text-xs sm:text-sm">
              Panel
            </TabsTrigger>
            <TabsTrigger value="reservaciones" className="text-xs sm:text-sm">
              Reservaciones
            </TabsTrigger>
            <TabsTrigger value="catalogo" className="text-xs sm:text-sm">
              Catálogo
            </TabsTrigger>
            <TabsTrigger value="config" className="text-xs sm:text-sm">
              Configuración
            </TabsTrigger>
          </TabsList>

          <TabsContent value="dashboard" className="mt-5">
            <DashboardTab onOpenReservations={() => setTab('reservaciones')} />
          </TabsContent>
          <TabsContent value="reservaciones" className="mt-5">
            <ReservationsTab toast={toast} />
          </TabsContent>
          <TabsContent value="catalogo" className="mt-5">
            <CatalogTab toast={toast} />
          </TabsContent>
          <TabsContent value="config" className="mt-5">
            <SettingsTab toast={toast} />
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}

/* --------------------------- Dashboard --------------------------- */
function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="precio mt-1 text-2xl font-bold">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

function DashboardTab({ onOpenReservations }: { onOpenReservations: () => void }) {
  const [data, setData] = useState<Dashboard | null>(null);
  const [error, setError] = useState('');

  const load = useCallback(() => {
    api<Dashboard>('/api/v1/crm/dashboard')
      .then(setData)
      .catch((e) => setError(apiError(e, 'No pudimos cargar el panel.')));
  }, []);

  useEffect(load, [load]);

  if (error) {
    return (
      <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-5">
        <p className="text-sm font-semibold text-destructive">{error}</p>
        <Button className="tap mt-3 rounded-full" onClick={load}>
          Volver a intentar
        </Button>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-5">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Nuevas sin leer" value={String(data.unread_count)} hint="Requieren confirmación" />
        <StatCard label="Entregas de hoy" value={String(data.today_count)} />
        <StatCard label="Próximas 7 días" value={String(data.upcoming_count)} />
        <StatCard label="Vencidas" value={String(data.expired_count)} hint="Inventario liberado" />
        <StatCard
          label="Total esperado"
          value={pesos(data.expected_total)}
          hint="Apartados activos por cobrar"
        />
        <StatCard
          label="Total entregado"
          value={pesos(data.delivered_total)}
          hint={`${data.delivered_count} entregas completadas`}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <section className="rounded-2xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base">
            <CalendarDays className="h-4 w-4 text-primary" /> Entregas de hoy
          </h2>
          {data.today_deliveries.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">No hay entregas programadas para hoy.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {data.today_deliveries.map((item) => (
                <li key={item.id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="precio text-sm font-semibold">{item.folio}</p>
                    <p className="truncate text-xs text-muted-foreground">
                      {item.customer_name} · {item.delivery_point_name}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="precio text-sm font-semibold">{pesos(item.total_amount)}</p>
                    <p className="precio text-xs text-muted-foreground">
                      {item.slot_start}–{item.slot_end}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base">
            <BadgeCheck className="h-4 w-4 text-primary" /> Nuevas sin leer
          </h2>
          {data.unread.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Todo está revisado.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {data.unread.map((item) => (
                <li key={item.id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="precio text-sm font-semibold">{item.folio}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.customer_name}</p>
                  </div>
                  <div className="text-right">
                    <p className="precio text-sm font-semibold">{pesos(item.total_amount)}</p>
                    <p className="precio text-xs text-muted-foreground">
                      {fechaCorta(item.delivery_date)}
                    </p>
                  </div>
                </li>
              ))}
            </ul>
          )}
          <Button className="tap mt-3 rounded-full" onClick={onOpenReservations}>
            Abrir reservaciones
          </Button>
        </section>

        <section className="rounded-2xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base">
            <Boxes className="h-4 w-4 text-primary" /> Poco inventario
          </h2>
          {data.low_stock.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Todo el inventario está en buen nivel.</p>
          ) : (
            <ul className="mt-3 divide-y divide-border">
              {data.low_stock.map((item) => (
                <li key={item.variant_id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium">{item.product_name}</p>
                    <p className="truncate text-xs text-muted-foreground">{item.variant_label}</p>
                  </div>
                  <span
                    className={`precio rounded-full px-2.5 py-1 text-xs font-semibold ${
                      item.available_units === 0
                        ? 'bg-destructive/15 text-destructive'
                        : 'bg-accent text-accent-foreground'
                    }`}
                  >
                    {item.available_units} libres
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        <section className="rounded-2xl border border-border bg-card p-4">
          <h2 className="text-base">Actividad reciente</h2>
          {data.activity.length === 0 ? (
            <p className="mt-3 text-sm text-muted-foreground">Sin movimientos todavía.</p>
          ) : (
            <ul className="mt-3 space-y-2.5">
              {data.activity.map((item) => (
                <li key={item.id} className="text-sm">
                  <span className="precio font-semibold">{item.folio || 'Reservación'}</span>{' '}
                  <span className="text-muted-foreground">→ {item.to_status_label}</span>
                  <p className="text-xs text-muted-foreground">
                    {fechaHora(item.created_at)}
                    {item.admin_email ? ` · ${item.admin_email}` : ''}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>
    </div>
  );
}

/* ----------------------------- Fotos ----------------------------- */
type ToastFn = ReturnType<typeof useToast>['toast'];

/** Botón que abre la cámara o la galería y sube las fotos elegidas. */
function PhotoButton({
  id,
  label,
  multiple = false,
  toast,
  onUploaded,
}: {
  id: string;
  label: string;
  multiple?: boolean;
  toast: ToastFn;
  onUploaded: (urls: string[]) => void;
}) {
  const [uploading, setUploading] = useState(false);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    const urls: string[] = [];
    try {
      for (const file of Array.from(files)) {
        urls.push(await uploadImage(file));
      }
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setUploading(false);
      if (urls.length > 0) onUploaded(urls);
    }
  };

  return (
    <label
      htmlFor={id}
      className="tap inline-flex cursor-pointer items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-medium focus-within:ring-2 focus-within:ring-ring"
    >
      {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
      {uploading ? 'Subiendo…' : label}
      <input
        id={id}
        type="file"
        accept="image/*"
        multiple={multiple}
        disabled={uploading}
        className="sr-only"
        onChange={(e) => {
          void handleFiles(e.target.files);
          e.target.value = '';
        }}
      />
    </label>
  );
}

/** Una sola foto: logotipo, portada o imagen de categoría. */
function PhotoField({
  id,
  label,
  value,
  toast,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  toast: ToastFn;
  onChange: (url: string) => void;
}) {
  return (
    <div>
      <p className="text-sm font-medium">{label}</p>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        {value ? (
          <img src={value} alt="" className="h-16 w-16 rounded-lg border border-border object-cover" />
        ) : null}
        <PhotoButton
          id={id}
          label={value ? 'Cambiar foto' : 'Subir foto'}
          toast={toast}
          onUploaded={(urls) => onChange(urls[0])}
        />
        {value ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-xs text-destructive"
            onClick={() => onChange('')}
          >
            Quitar
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Fotos de un producto; la primera es la principal en catálogo y redes. */
function ProductPhotos({
  images,
  name,
  toast,
  onChange,
}: {
  images: CatalogProduct['images'];
  name: string;
  toast: ToastFn;
  onChange: (images: CatalogProduct['images']) => void;
}) {
  return (
    <div className="sm:col-span-2">
      <p className="text-sm font-medium">Fotos</p>
      <p className="text-xs text-muted-foreground">La primera foto es la principal.</p>
      <ul className="mt-2 flex flex-wrap gap-3">
        {images.map((image, index) => (
          <li key={`${image.url}-${index}`} className="w-24">
            <img
              src={image.url}
              alt={image.alt_text || name}
              className={`h-24 w-24 rounded-lg object-cover ${index === 0 ? 'ring-2 ring-primary' : 'border border-border'}`}
            />
            <div className="mt-1 flex justify-between">
              {index === 0 ? (
                <span className="text-xs font-semibold text-primary">Principal</span>
              ) : (
                <button
                  type="button"
                  className="text-xs underline"
                  onClick={() => onChange([image, ...images.filter((_, i) => i !== index)])}
                >
                  Principal
                </button>
              )}
              <button
                type="button"
                className="text-xs text-destructive underline"
                aria-label={`Quitar foto ${index + 1}`}
                onClick={() => onChange(images.filter((_, i) => i !== index))}
              >
                Quitar
              </button>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-2">
        <PhotoButton
          id="p-fotos"
          label="Agregar fotos"
          multiple
          toast={toast}
          onUploaded={(urls) =>
            onChange([...images, ...urls.map((url) => ({ id: 0, url, alt_text: name }))])
          }
        />
      </div>
    </div>
  );
}

/* ------------------------- Reservaciones ------------------------- */

function ReservationsTab({ toast }: { toast: ToastFn }) {
  const [rows, setRows] = useState<ReservationRow[]>([]);
  const [statuses, setStatuses] = useState<StatusOption[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ReservationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [note, setNote] = useState('');
  const [statusNote, setStatusNote] = useState('');
  const [working, setWorking] = useState(false);
  const [privateLink, setPrivateLink] = useState('');
  const [linkDeliveryStatus, setLinkDeliveryStatus] = useState('');

  const load = useCallback(() => {
    setLoading(true);
    api<{ items: ReservationRow[]; statuses: StatusOption[] }>(
      '/api/v1/crm/reservations',
      'GET',
      {
        search,
        status: statusFilter === 'all' ? '' : statusFilter,
        date_from: dateFrom,
        date_to: dateTo,
      },
    )
      .then((result) => {
        setRows(result.items);
        setStatuses(result.statuses);
      })
      .catch((e) => toast({ title: apiError(e), variant: 'destructive' }))
      .finally(() => setLoading(false));
  }, [search, statusFilter, dateFrom, dateTo, toast]);

  useEffect(() => {
    const timer = window.setTimeout(load, 220);
    return () => window.clearTimeout(timer);
  }, [load]);

  const openDetail = async (id: number) => {
    setSelected(id);
    setDetailLoading(true);
    setDetail(null);
    setPrivateLink('');
    setLinkDeliveryStatus('');
    try {
      const result = await api<ReservationDetail>(`/api/v1/crm/reservations/${id}`);
      setDetail(result);
      setNote(result.reservation.internal_notes);
      if (result.reservation.is_unread) {
        await api(`/api/v1/crm/reservations/${id}/read`, 'POST');
        setRows((prev) => prev.map((r) => (r.id === id ? { ...r, is_unread: false } : r)));
      }
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setDetailLoading(false);
    }
  };

  const changeStatus = async (status: string) => {
    if (!selected) return;
    setWorking(true);
    try {
      const result = await api<{ reservation: Reservation; email_status: { status: string }[] }>(
        `/api/v1/crm/reservations/${selected}/status`,
        'POST',
        { status, note: statusNote },
      );
      setDetail((prev) => (prev ? { ...prev, reservation: result.reservation } : prev));
      setStatusNote('');
      const failed = (result.email_status || []).filter((e) => e.status !== 'enviado');
      toast({
        title: `Estado actualizado a ${result.reservation.status_label}`,
        description:
          failed.length > 0
            ? 'El correo no se envió. Revisa la bitácora para reenviarlo.'
            : undefined,
      });
      await openDetail(selected);
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const saveNote = async () => {
    if (!selected) return;
    setWorking(true);
    try {
      await api(`/api/v1/crm/reservations/${selected}/note`, 'POST', { internal_notes: note });
      toast({ title: 'Nota interna guardada' });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const generateAndSendPrivateLink = async () => {
    if (!selected) return;
    if (!window.confirm('Generar un enlace nuevo invalidará inmediatamente el enlace anterior. ¿Continuar?')) {
      return;
    }
    setWorking(true);
    try {
      const result = await api<{
        private_token: string;
        email_sent: boolean;
        recovery_required: boolean;
        message: string;
        email_status: { status: string; error?: string }[];
        notifications: NotificationRow[];
      }>(`/api/v1/crm/reservations/${selected}/rotate-confirmation-token`, 'POST');
      const link = `${window.location.origin}/confirmacion#t=${result.private_token}`;
      setPrivateLink(link);
      setLinkDeliveryStatus(result.message);
      setDetail((prev) => (prev ? { ...prev, notifications: result.notifications } : prev));
      toast({
        title: result.email_sent ? 'Enlace nuevo enviado' : 'Copia el enlace nuevo',
        description: result.message,
        variant: result.email_sent ? undefined : 'destructive',
      });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const copyPrivateLink = async () => {
    if (!privateLink) return;
    try {
      await navigator.clipboard.writeText(privateLink);
      toast({ title: 'Enlace privado copiado' });
    } catch {
      toast({ title: 'No pudimos copiar el enlace', variant: 'destructive' });
    }
  };

  const revokePrivateLink = async () => {
    if (!selected) return;
    if (!window.confirm('Revocar el enlace impedirá que la clienta vuelva a abrirlo. ¿Continuar?')) {
      return;
    }
    setWorking(true);
    try {
      await api(`/api/v1/crm/reservations/${selected}/revoke-confirmation-token`, 'POST');
      setPrivateLink('');
      setLinkDeliveryStatus('El enlace privado quedó revocado.');
      toast({ title: 'Enlace privado revocado' });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const resend = async (template: string) => {
    if (!selected) return;
    setWorking(true);
    try {
      const result = await api<{ email_status: { status: string; error?: string }[]; notifications: NotificationRow[] }>(
        `/api/v1/crm/reservations/${selected}/resend`,
        'POST',
        { template },
      );
      setDetail((prev) => (prev ? { ...prev, notifications: result.notifications } : prev));
      const first = result.email_status[0];
      toast({
        title:
          first?.status === 'enviado'
            ? 'Correo reenviado correctamente'
            : 'El correo no se pudo enviar',
        description: first?.status !== 'enviado' ? first?.error : undefined,
        variant: first?.status === 'enviado' ? undefined : 'destructive',
      });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const exportCsv = async () => {
    try {
      const response = await downloadApi(
        '/api/v1/crm/reservations-export',
        {
          search,
          status: statusFilter === 'all' ? '' : statusFilter,
          date_from: dateFrom,
          date_to: dateTo,
        },
      );
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      const disposition = response.headers.get('Content-Disposition') || '';
      const filename = disposition.match(/filename="([^"]+)"/i)?.[1] || 'reservaciones.csv';
      link.download = filename;
      link.click();
      URL.revokeObjectURL(url);
      const count = Number(response.headers.get('X-Exported-Rows') || 0);
      toast({ title: `Exportamos ${count} reservaciones` });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    }
  };

  return (
    <div className="grid gap-5 lg:grid-cols-[minmax(0,1fr)_minmax(0,420px)]">
      <div>
        <div className="space-y-3 rounded-2xl border border-border bg-card p-4">
          <div className="relative">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
            <Label htmlFor="crm-buscar" className="sr-only">
              Buscar por folio, nombre, WhatsApp o correo
            </Label>
            <Input
              id="crm-buscar"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Folio, nombre, WhatsApp o correo"
              className="tap pl-9"
            />
          </div>
          <div className="grid gap-2 sm:grid-cols-3">
            <div>
              <Label htmlFor="crm-estado" className="text-xs">
                Estado
              </Label>
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger id="crm-estado" className="tap mt-1">
                  <SelectValue placeholder="Todos" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">Todos</SelectItem>
                  {statuses.map((s) => (
                    <SelectItem key={s.value} value={s.value}>
                      {s.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div>
              <Label htmlFor="crm-desde" className="text-xs">
                Desde
              </Label>
              <Input
                id="crm-desde"
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="crm-hasta" className="text-xs">
                Hasta
              </Label>
              <Input
                id="crm-hasta"
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="tap mt-1"
              />
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" className="tap rounded-full !bg-transparent hover:!bg-transparent" onClick={load}>
              <RefreshCw className="mr-2 h-4 w-4" /> Actualizar
            </Button>
            <Button variant="outline" className="tap rounded-full !bg-transparent hover:!bg-transparent" onClick={exportCsv}>
              <Download className="mr-2 h-4 w-4" /> Exportar CSV
            </Button>
          </div>
        </div>

        <div className="mt-4 space-y-2">
          {loading ? (
            [0, 1, 2].map((i) => <Skeleton key={i} className="h-20 rounded-2xl" />)
          ) : rows.length === 0 ? (
            <p className="rounded-2xl border border-border bg-card p-5 text-sm text-muted-foreground">
              No hay reservaciones con esos filtros.
            </p>
          ) : (
            rows.map((row) => (
              <button
                key={row.id}
                type="button"
                onClick={() => openDetail(row.id)}
                className={`w-full rounded-2xl border p-4 text-left transition-colors ${
                  selected === row.id ? 'border-primary bg-accent' : 'border-border bg-card'
                }`}
              >
                <div className="flex items-start gap-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="precio text-sm font-bold">{row.folio}</span>
                      {row.is_unread ? (
                        <span className="h-2 w-2 rounded-full bg-primary" aria-label="Sin leer" />
                      ) : null}
                    </div>
                    <p className="truncate text-sm">{row.customer_name}</p>
                    <p className="precio truncate text-xs text-muted-foreground">
                      {fechaCorta(row.delivery_date)} · {row.slot_start}–{row.slot_end} ·{' '}
                      {row.delivery_point_name}
                    </p>
                  </div>
                  <div className="text-right">
                    <p className="precio text-sm font-bold">{pesos(row.total_amount)}</p>
                    <span className="mt-1 inline-block rounded-full bg-secondary px-2 py-0.5 text-[11px] font-semibold text-secondary-foreground">
                      {row.status_label}
                    </span>
                  </div>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      {/* Detalle */}
      <aside className="lg:sticky lg:top-24 lg:self-start">
        {!selected ? (
          <div className="rounded-2xl border border-border bg-card p-5">
            <p className="text-sm text-muted-foreground">
              Selecciona una reservación para ver su detalle, cambiar el estado y revisar los correos.
            </p>
          </div>
        ) : detailLoading || !detail ? (
          <div className="space-y-3">
            <Skeleton className="h-32 rounded-2xl" />
            <Skeleton className="h-24 rounded-2xl" />
          </div>
        ) : (
          <div className="space-y-4">
            <section className="rounded-2xl border border-border bg-card p-4">
              <p className="precio text-lg font-bold">{detail.reservation.folio}</p>
              <p className="text-sm text-muted-foreground">{detail.reservation.status_label}</p>
              <dl className="mt-3 space-y-1 text-sm">
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Clienta</dt>
                  <dd className="text-right font-medium">{detail.reservation.customer_name}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">WhatsApp</dt>
                  <dd className="precio text-right">
                    <a
                      className="text-primary underline-offset-4 hover:underline"
                      href={`https://wa.me/52${detail.reservation.customer_whatsapp}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {detail.reservation.customer_whatsapp}
                    </a>
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Correo</dt>
                  <dd className="break-all text-right">{detail.reservation.customer_email}</dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Entrega</dt>
                  <dd className="precio text-right">
                    {fechaCorta(detail.reservation.delivery_date)} {detail.reservation.slot_start}–
                    {detail.reservation.slot_end}
                  </dd>
                </div>
                <div className="flex justify-between gap-2">
                  <dt className="text-muted-foreground">Punto</dt>
                  <dd className="text-right">{detail.reservation.delivery_point_name}</dd>
                </div>
              </dl>

              <ul className="mt-3 divide-y divide-border border-t border-border pt-2">
                {detail.reservation.items.map((item) => (
                  <li key={item.id} className="flex justify-between gap-2 py-2 text-sm">
                    <span className="min-w-0">
                      <span className="block truncate">{item.product_name}</span>
                      <span className="precio block text-xs text-muted-foreground">
                        {item.variant_label} · {item.quantity} pza
                      </span>
                    </span>
                    <span className="precio font-semibold">{pesos(item.line_total)}</span>
                  </li>
                ))}
              </ul>
              <div className="mt-2 flex justify-between border-t border-border pt-2">
                <span className="text-sm font-semibold">Total a cobrar</span>
                <span className="precio text-lg font-bold text-primary">
                  {pesos(detail.reservation.total_amount)}
                </span>
              </div>
              {detail.reservation.customer_notes ? (
                <p className="mt-3 rounded-lg bg-secondary p-3 text-xs leading-relaxed">
                  Nota de la clienta: {detail.reservation.customer_notes}
                </p>
              ) : null}
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Cambiar estado</h3>
              <Textarea
                value={statusNote}
                onChange={(e) => setStatusNote(e.target.value)}
                rows={2}
                placeholder="Motivo o nota del cambio (opcional)"
                className="mt-2 text-sm"
              />
              <div className="mt-2 flex flex-wrap gap-2">
                {detail.statuses
                  .filter((s) => s.value !== detail.reservation.status)
                  .map((s) => (
                    <Button
                      key={s.value}
                      size="sm"
                      variant="outline"
                      disabled={working}
                      onClick={() => changeStatus(s.value)}
                      className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                    >
                      {s.label}
                    </Button>
                  ))}
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Nota interna</h3>
              <Textarea
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                className="mt-2 text-sm"
                placeholder="Solo visible para el equipo."
              />
              <Button size="sm" className="tap mt-2 rounded-full" onClick={saveNote} disabled={working}>
                Guardar nota
              </Button>
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Link2 className="h-4 w-4 text-primary" /> Enlace privado
              </h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Generar un enlace nuevo invalida el anterior. El token sólo permanecerá temporalmente
                en esta pantalla y no se guardará en el navegador.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  size="sm"
                  disabled={
                    working || !ACTIVE_RESERVATION_STATUSES.has(detail.reservation.status)
                  }
                  onClick={generateAndSendPrivateLink}
                  className="rounded-full"
                >
                  <Link2 className="mr-2 h-4 w-4" /> Generar y enviar nuevo enlace
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={working}
                  onClick={revokePrivateLink}
                  className="rounded-full !bg-transparent"
                >
                  <Unlink className="mr-2 h-4 w-4" /> Revocar enlace
                </Button>
              </div>
              {privateLink ? (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
                  <Label htmlFor="crm-enlace-privado" className="text-xs font-semibold text-amber-950">
                    Copia este enlace antes de cerrar o cambiar de reservación
                  </Label>
                  <div className="mt-2 flex gap-2">
                    <Input
                      id="crm-enlace-privado"
                      value={privateLink}
                      readOnly
                      className="font-mono text-xs"
                    />
                    <Button size="sm" type="button" onClick={copyPrivateLink}>
                      <Copy className="mr-2 h-4 w-4" /> Copiar enlace
                    </Button>
                  </div>
                </div>
              ) : null}
              {linkDeliveryStatus ? (
                <p className="mt-2 text-xs font-medium">{linkDeliveryStatus}</p>
              ) : null}
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Mail className="h-4 w-4 text-primary" /> Correos enviados
              </h3>
              {detail.notifications.length === 0 ? (
                <p className="mt-2 text-xs text-muted-foreground">Aún no hay correos registrados.</p>
              ) : (
                <ul className="mt-2 space-y-2">
                  {detail.notifications.map((n) => (
                    <li key={n.id} className="rounded-lg border border-border p-2.5 text-xs">
                      <div className="flex items-start justify-between gap-2">
                        <span className="font-medium">
                          {TEMPLATE_LABELS[n.template] || n.template}
                        </span>
                        <span className={`font-semibold ${EMAIL_STATUS_TONE[n.status] || ''}`}>
                          {n.status}
                        </span>
                      </div>
                      <p className="mt-0.5 break-all text-muted-foreground">{n.recipient_email}</p>
                      {n.error_message ? (
                        <p className="mt-1 text-destructive">{n.error_message}</p>
                      ) : null}
                      <Button
                        size="sm"
                        variant="ghost"
                        disabled={working}
                        onClick={() =>
                          LINK_EMAIL_TEMPLATES.has(n.template)
                            ? generateAndSendPrivateLink()
                            : resend(n.template)
                        }
                        className="mt-1 h-8 px-0 text-xs text-primary"
                      >
                        {LINK_EMAIL_TEMPLATES.has(n.template) ? 'Generar enlace nuevo' : 'Reenviar'}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <div className="mt-3 flex flex-wrap gap-2 border-t border-border pt-3">
                {Object.keys(TEMPLATE_LABELS)
                  .filter((template) => !LINK_EMAIL_TEMPLATES.has(template))
                  .map((template) => (
                  <Button
                    key={template}
                    size="sm"
                    variant="outline"
                    disabled={working}
                    onClick={() => resend(template)}
                    className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                  >
                    {TEMPLATE_LABELS[template]}
                  </Button>
                  ))}
              </div>
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Historial</h3>
              <ul className="mt-2 space-y-2 text-xs">
                {detail.history.map((h) => (
                  <li key={h.id}>
                    <span className="font-medium">{h.to_status_label}</span>
                    <span className="text-muted-foreground"> · {fechaHora(h.created_at)}</span>
                    {h.admin_email ? (
                      <span className="text-muted-foreground"> · {h.admin_email}</span>
                    ) : null}
                    {h.note ? <p className="text-muted-foreground">{h.note}</p> : null}
                  </li>
                ))}
              </ul>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

/* ---------------------------- Catálogo --------------------------- */
function CatalogTab({ toast }: { toast: ToastFn }) {
  const [data, setData] = useState<CatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<CatalogProduct | null>(null);
  const [working, setWorking] = useState(false);
  const [stockDrafts, setStockDrafts] = useState<Record<number, string>>({});

  const load = useCallback(() => {
    setLoading(true);
    api<CatalogResponse>('/api/v1/crm/catalog')
      .then(setData)
      .catch((e) => toast({ title: apiError(e), variant: 'destructive' }))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  const blank: CatalogProduct = useMemo(
    () => ({
      id: 0,
      name: '',
      slug: '',
      short_description: '',
      full_description: '',
      ingredients: '',
      usage_instructions: '',
      category_id: data?.categories[0]?.id ?? null,
      price: 0,
      tags: '',
      is_active: true,
      is_featured: false,
      is_archived: false,
      sort_order: 0,
      images: [],
      variants: [],
    }),
    [data],
  );

  const saveProduct = async () => {
    if (!editing) return;
    if (!editing.name.trim() || !editing.slug.trim() || editing.price <= 0) {
      toast({ title: 'Nombre, slug y precio son obligatorios.', variant: 'destructive' });
      return;
    }
    setWorking(true);
    try {
      const payload = {
        name: editing.name,
        slug: editing.slug,
        short_description: editing.short_description,
        full_description: editing.full_description,
        ingredients: editing.ingredients,
        usage_instructions: editing.usage_instructions,
        category_id: editing.category_id,
        price: editing.price,
        tags: editing.tags,
        is_active: editing.is_active,
        is_featured: editing.is_featured,
        is_archived: editing.is_archived,
        sort_order: editing.sort_order,
        images: editing.images.map((i) => i.url).filter(Boolean),
      };
      if (editing.id === 0) {
        await api('/api/v1/crm/products', 'POST', payload);
      } else {
        await api(`/api/v1/crm/products/${editing.id}`, 'PUT', payload);
      }
      toast({ title: 'Producto guardado' });
      setEditing(null);
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const adjustStock = async (variantId: number) => {
    const raw = stockDrafts[variantId];
    if (raw === undefined || raw === '') return;
    setWorking(true);
    try {
      await api('/api/v1/crm/stock-adjust', 'POST', {
        variant_id: variantId,
        new_stock: Number(raw),
        note: 'Ajuste manual desde el catálogo',
      });
      toast({ title: 'Inventario actualizado' });
      setStockDrafts((prev) => ({ ...prev, [variantId]: '' }));
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const removeProduct = async (product: CatalogProduct) => {
    setWorking(true);
    try {
      await api(`/api/v1/crm/products/${product.id}`, 'DELETE');
      toast({ title: 'Producto eliminado' });
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  if (loading || !data) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button className="tap rounded-full" onClick={() => setEditing(blank)}>
          Nuevo producto
        </Button>
        <Button
          variant="outline"
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
          onClick={load}
        >
          <RefreshCw className="mr-2 h-4 w-4" /> Actualizar
        </Button>
        <span className="precio text-sm text-muted-foreground">
          {data.products.length} productos · {data.categories.length} categorías
        </span>
      </div>

      {editing ? (
        <section className="rounded-2xl border border-primary/40 bg-card p-4">
          <h2 className="text-base">{editing.id === 0 ? 'Nuevo producto' : `Editar: ${editing.name}`}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="p-nombre">Nombre</Label>
              <Input
                id="p-nombre"
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                className="tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-slug">Slug (URL)</Label>
              <Input
                id="p-slug"
                value={editing.slug}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'),
                  })
                }
                className="tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-precio">Precio MXN</Label>
              <Input
                id="p-precio"
                type="number"
                min={0}
                value={editing.price}
                onChange={(e) => setEditing({ ...editing, price: Number(e.target.value) })}
                className="precio tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-categoria">Categoría</Label>
              <Select
                value={editing.category_id ? String(editing.category_id) : ''}
                onValueChange={(value) => setEditing({ ...editing, category_id: Number(value) })}
              >
                <SelectTrigger id="p-categoria" className="tap mt-1">
                  <SelectValue placeholder="Selecciona" />
                </SelectTrigger>
                <SelectContent>
                  {data.categories.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-corta">Descripción corta</Label>
              <Input
                id="p-corta"
                value={editing.short_description}
                onChange={(e) => setEditing({ ...editing, short_description: e.target.value })}
                className="tap mt-1"
              />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-larga">Descripción completa</Label>
              <Textarea
                id="p-larga"
                rows={4}
                value={editing.full_description}
                onChange={(e) => setEditing({ ...editing, full_description: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-ing">Ingredientes</Label>
              <Textarea
                id="p-ing"
                rows={3}
                value={editing.ingredients}
                onChange={(e) => setEditing({ ...editing, ingredients: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-uso">Modo de uso</Label>
              <Textarea
                id="p-uso"
                rows={3}
                value={editing.usage_instructions}
                onChange={(e) => setEditing({ ...editing, usage_instructions: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-tags">Etiquetas (separadas por coma)</Label>
              <Input
                id="p-tags"
                value={editing.tags}
                onChange={(e) => setEditing({ ...editing, tags: e.target.value })}
                className="tap mt-1"
              />
            </div>
            <ProductPhotos
              images={editing.images}
              name={editing.name}
              toast={toast}
              onChange={(images) => setEditing((current) => (current ? { ...current, images } : current))}
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-4">
            {(
              [
                ['is_active', 'Visible en la tienda'],
                ['is_featured', 'Destacado en inicio'],
                ['is_archived', 'Archivado'],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(editing[key])}
                  onChange={(e) => setEditing({ ...editing, [key]: e.target.checked })}
                  className="h-4 w-4 accent-primary"
                />
                {label}
              </label>
            ))}
          </div>

          <div className="mt-4 flex gap-2">
            <Button className="tap rounded-full" onClick={saveProduct} disabled={working}>
              {working ? 'Guardando…' : 'Guardar producto'}
            </Button>
            <Button
              variant="outline"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
              onClick={() => setEditing(null)}
            >
              Cancelar
            </Button>
          </div>
        </section>
      ) : null}

      <div className="space-y-3">
        {data.products.map((product) => (
          <section key={product.id} className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-start gap-3">
              {product.images[0] ? (
                <img
                  src={product.images[0].url}
                  alt={product.name}
                  loading="lazy"
                  className="h-16 w-16 flex-shrink-0 rounded-lg object-cover"
                />
              ) : null}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{product.name}</p>
                <p className="precio text-xs text-muted-foreground">
                  {pesos(product.price)} · {product.variants.length} variantes
                  {product.is_featured ? ' · destacado' : ''}
                  {!product.is_active ? ' · oculto' : ''}
                  {product.is_archived ? ' · archivado' : ''}
                </p>
              </div>
              <div className="flex flex-shrink-0 flex-col gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                  onClick={() => setEditing(product)}
                >
                  Editar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-xs text-destructive"
                  disabled={working}
                  onClick={() => removeProduct(product)}
                >
                  Eliminar
                </Button>
              </div>
            </div>

            <ul className="mt-3 space-y-2 border-t border-border pt-3">
              {product.variants.map((variant) => (
                <li key={variant.id} className="flex flex-wrap items-center gap-2 text-sm">
                  <span className="min-w-0 flex-1 truncate">{variant.label}</span>
                  <span className="precio text-xs text-muted-foreground">
                    {variant.available_units} libres / {variant.stock} totales
                    {variant.reserved_stock > 0 ? ` · ${variant.reserved_stock} apartadas` : ''}
                  </span>
                  <Input
                    type="number"
                    min={0}
                    value={stockDrafts[variant.id] ?? ''}
                    onChange={(e) =>
                      setStockDrafts((prev) => ({ ...prev, [variant.id]: e.target.value }))
                    }
                    placeholder="Nuevo"
                    aria-label={`Nuevo inventario para ${variant.label}`}
                    className="precio h-9 w-24"
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    disabled={working || !stockDrafts[variant.id]}
                    onClick={() => adjustStock(variant.id)}
                    className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                  >
                    Ajustar
                  </Button>
                </li>
              ))}
              {product.variants.length === 0 ? (
                <li className="text-xs text-muted-foreground">Sin variantes registradas.</li>
              ) : null}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}

/* -------------------------- Configuración ------------------------ */
function SettingsTab({ toast }: { toast: ToastFn }) {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [delivery, setDelivery] = useState<DeliveryConfig | null>(null);
  const [store, setStore] = useState<Record<string, string | number>>({});
  const [priv, setPriv] = useState<Record<string, string>>({});
  const [working, setWorking] = useState(false);

  const load = useCallback(() => {
    Promise.all([
      api<SettingsResponse>('/api/v1/crm/settings'),
      api<DeliveryConfig>('/api/v1/crm/delivery'),
    ])
      .then(([settings, deliveryConfig]) => {
        setData(settings);
        setStore(settings.store);
        setPriv(settings.private);
        setDelivery(deliveryConfig);
      })
      .catch((e) => toast({ title: apiError(e), variant: 'destructive' }));
  }, [toast]);

  useEffect(load, [load]);

  const saveStore = async () => {
    setWorking(true);
    try {
      await api('/api/v1/crm/settings/store', 'PUT', store);
      toast({ title: 'Identidad y contenido guardados' });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const savePrivate = async () => {
    setWorking(true);
    try {
      await api('/api/v1/crm/settings/private', 'PUT', priv);
      toast({ title: 'Datos privados guardados' });
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const savePoint = async (point: DeliveryConfig['points'][number]) => {
    setWorking(true);
    try {
      await api(`/api/v1/crm/delivery-points/${point.id}`, 'PUT', point);
      toast({ title: 'Punto de entrega actualizado' });
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  if (!data || !delivery) {
    return (
      <div className="space-y-2">
        {[0, 1].map((i) => (
          <Skeleton key={i} className="h-32 rounded-2xl" />
        ))}
      </div>
    );
  }

  const textField = (key: string, label: string, multiline = false, rows = 4) => (
    <div className={multiline ? 'sm:col-span-2' : ''}>
      <Label htmlFor={`s-${key}`}>{label}</Label>
      {multiline ? (
        <Textarea
          id={`s-${key}`}
          rows={rows}
          value={String(store[key] ?? '')}
          onChange={(e) => setStore({ ...store, [key]: e.target.value })}
          className="mt-1"
        />
      ) : (
        <Input
          id={`s-${key}`}
          value={String(store[key] ?? '')}
          onChange={(e) => setStore({ ...store, [key]: e.target.value })}
          className="tap mt-1"
        />
      )}
    </div>
  );

  return (
    <div className="space-y-5">
      {!data.email_provider_configured ? (
        <div className="flex items-start gap-3 rounded-2xl border border-amber-500/50 bg-amber-500/10 p-4">
          <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-amber-700" />
          <div>
            <p className="text-sm font-semibold text-amber-900">Falta configurar el envío de correos</p>
            <p className="mt-1 text-sm leading-relaxed text-amber-900/85">
              Agrega la clave de Resend en la plataforma para que los correos a las clientas y las alertas
              al negocio se envíen de verdad. Mientras no esté configurada, quedarán registrados como
              pendientes y podrás reenviarlos desde cada reservación.
            </p>
          </div>
        </div>
      ) : null}

      <section className="rounded-2xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-base">
          <SettingsIcon className="h-4 w-4 text-primary" /> Identidad de la tienda
        </h2>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {textField('shop_name', 'Nombre de la tienda')}
          {textField('tagline', 'Frase de marca')}
          <PhotoField
            id="s-logo"
            label="Logotipo"
            value={String(store.logo_url ?? '')}
            toast={toast}
            onChange={(url) => setStore((current) => ({ ...current, logo_url: url }))}
          />
          <PhotoField
            id="s-hero"
            label="Imagen de portada"
            value={String(store.hero_image_url ?? '')}
            toast={toast}
            onChange={(url) => setStore((current) => ({ ...current, hero_image_url: url }))}
          />
          {textField('color_bg', 'Color de fondo')}
          {textField('color_text', 'Color de texto')}
          {textField('color_accent', 'Color de acento')}
          {textField('contact_email', 'Correo de contacto')}
          {textField('contact_whatsapp', 'WhatsApp público (10 dígitos)')}
          {textField('instagram_url', 'Instagram')}
          {textField('tiktok_url', 'TikTok')}
          {textField('facebook_url', 'Facebook')}
          <div>
            <Label htmlFor="s-window">Días hacia adelante para apartar</Label>
            <Input
              id="s-window"
              type="number"
              min={1}
              max={60}
              value={Number(store.reservation_window_days ?? 7)}
              onChange={(e) => setStore({ ...store, reservation_window_days: Number(e.target.value) })}
              className="precio tap mt-1"
            />
          </div>
          <div>
            <Label htmlFor="s-grace">Horas de gracia antes de vencer</Label>
            <Input
              id="s-grace"
              type="number"
              min={0}
              max={72}
              value={Number(store.grace_period_hours ?? 2)}
              onChange={(e) => setStore({ ...store, grace_period_hours: Number(e.target.value) })}
              className="precio tap mt-1"
            />
          </div>
          {textField('delivery_instructions', 'Instrucciones de entrega', true, 3)}
          {textField('how_it_works', 'Cómo funciona', true, 6)}
          {textField('faq_content', 'Preguntas frecuentes (pregunta|respuesta por línea)', true, 6)}
          {textField('reservation_policy', 'Políticas de apartado', true, 6)}
          {textField('privacy_policy', 'Aviso de privacidad', true, 6)}
        </div>
        <Button className="tap mt-4 rounded-full" onClick={saveStore} disabled={working}>
          Guardar identidad y contenido
        </Button>
      </section>

      <section className="rounded-2xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4 text-primary" /> Datos privados
        </h2>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Los datos bancarios solo se muestran en la confirmación privada de cada clienta y nunca aparecen
          en el catálogo público.
        </p>
        <div className="mt-3 grid gap-3 sm:grid-cols-2">
          {(
            [
              ['bank_name', 'Banco'],
              ['account_holder', 'Titular de la cuenta'],
              ['clabe', 'CLABE'],
              ['account_number', 'Número de cuenta'],
              ['alert_recipients', 'Correos para alertas (separados por coma)'],
              ['notification_from_email', 'Correo remitente verificado'],
              ['notification_from_name', 'Nombre del remitente'],
            ] as const
          ).map(([key, label]) => (
            <div key={key}>
              <Label htmlFor={`pv-${key}`}>{label}</Label>
              <Input
                id={`pv-${key}`}
                value={priv[key] ?? ''}
                onChange={(e) => setPriv({ ...priv, [key]: e.target.value })}
                className="tap mt-1"
              />
            </div>
          ))}
          <div className="sm:col-span-2">
            <Label htmlFor="pv-instr">Instrucciones de transferencia</Label>
            <Textarea
              id="pv-instr"
              rows={3}
              value={priv.transfer_instructions ?? ''}
              onChange={(e) => setPriv({ ...priv, transfer_instructions: e.target.value })}
              className="mt-1"
            />
          </div>
        </div>
        <Button className="tap mt-4 rounded-full" onClick={savePrivate} disabled={working}>
          Guardar datos privados
        </Button>
      </section>

      <section className="rounded-2xl border border-border bg-card p-4">
        <h2 className="flex items-center gap-2 text-base">
          <MapPin className="h-4 w-4 text-primary" /> Puntos de entrega y horarios
        </h2>
        <div className="mt-3 space-y-4">
          {delivery.points.map((point) => {
            const slots = delivery.slots.filter((s) => s.delivery_point_id === point.id);
            return (
              <div key={point.id} className="rounded-xl border border-border p-3">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <Label htmlFor={`dp-name-${point.id}`}>Nombre</Label>
                    <Input
                      id={`dp-name-${point.id}`}
                      value={point.name}
                      onChange={(e) =>
                        setDelivery({
                          ...delivery,
                          points: delivery.points.map((p) =>
                            p.id === point.id ? { ...p, name: e.target.value } : p,
                          ),
                        })
                      }
                      className="tap mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor={`dp-ref-${point.id}`}>Punto de encuentro</Label>
                    <Input
                      id={`dp-ref-${point.id}`}
                      value={point.reference}
                      onChange={(e) =>
                        setDelivery({
                          ...delivery,
                          points: delivery.points.map((p) =>
                            p.id === point.id ? { ...p, reference: e.target.value } : p,
                          ),
                        })
                      }
                      className="tap mt-1"
                    />
                  </div>
                  <div className="sm:col-span-2">
                    <Label htmlFor={`dp-addr-${point.id}`}>Dirección</Label>
                    <Input
                      id={`dp-addr-${point.id}`}
                      value={point.address}
                      onChange={(e) =>
                        setDelivery({
                          ...delivery,
                          points: delivery.points.map((p) =>
                            p.id === point.id ? { ...p, address: e.target.value } : p,
                          ),
                        })
                      }
                      className="tap mt-1"
                    />
                  </div>
                </div>
                <label className="mt-2 flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={point.is_active}
                    onChange={(e) =>
                      setDelivery({
                        ...delivery,
                        points: delivery.points.map((p) =>
                          p.id === point.id ? { ...p, is_active: e.target.checked } : p,
                        ),
                      })
                    }
                    className="h-4 w-4 accent-primary"
                  />
                  Activo para nuevas reservaciones
                </label>
                <p className="precio mt-2 text-xs text-muted-foreground">
                  Horarios:{' '}
                  {slots.length === 0
                    ? 'sin horarios'
                    : slots
                        .map(
                          (s) =>
                            `${WEEKDAY_NAMES[s.weekday]} ${s.start_time}–${s.end_time}${
                              s.capacity > 0 ? ` (${s.capacity})` : ''
                            }`,
                        )
                        .join(' · ')}
                </p>
                <Button
                  size="sm"
                  className="tap mt-2 rounded-full"
                  onClick={() => savePoint(point)}
                  disabled={working}
                >
                  Guardar punto
                </Button>
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
