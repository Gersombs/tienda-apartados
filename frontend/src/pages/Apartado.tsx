import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, Check, ChevronLeft, Clock, MapPin, Trash2 } from 'lucide-react';
import ShopLayout, { useCart } from '@/components/ShopLayout';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Checkbox } from '@/components/ui/checkbox';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import {
  AVISO_SIN_PAGO,
  DeliveryDay,
  DeliveryPoint,
  DeliverySlot,
  MESES,
  StoreSettings,
  api,
  apiError,
  cart,
  cartTotals,
  fechaLarga,
  fingerprint,
  pesos,
  setSeo,
  SHOP_NAME_FALLBACK,
} from '@/lib/shop';

interface Bootstrap {
  settings: StoreSettings;
}

interface OptionsResponse {
  delivery_points: DeliveryPoint[];
  reservation_window_days: number;
  grace_period_hours: number;
}

interface AvailabilityResponse {
  all_ok: boolean;
  lines: {
    variant_id: number;
    ok: boolean;
    available_units?: number;
    unit_price?: number;
    product_name?: string;
    variant_label?: string;
    reason?: string;
  }[];
}

interface CreatedResponse {
  folio: string;
  private_token: string;
  total_amount: number;
}

type Step = 'apartado' | 'entrega' | 'revision';

interface FormState {
  full_name: string;
  whatsapp: string;
  email: string;
  notes: string;
  privacy_accepted: boolean;
}

const EMPTY_FORM: FormState = {
  full_name: '',
  whatsapp: '',
  email: '',
  notes: '',
  privacy_accepted: false,
};

const PASOS = ['Entrega y datos', 'Revisa y envía', 'Listo'];

/** Dónde va la clienta en el proceso; en celular solo se nombra el paso actual. */
function Pasos({ actual }: { actual: number }) {
  return (
    <ol aria-label="Pasos del apartado" className="flex items-center gap-2 text-xs font-medium">
      {PASOS.map((paso, index) => (
        <li
          key={paso}
          aria-current={index === actual ? 'step' : undefined}
          className="flex items-center gap-2"
        >
          <span
            className={`precio flex h-6 w-6 items-center justify-center rounded-full ${
              index <= actual ? 'bg-primary text-primary-foreground' : 'bg-secondary text-muted-foreground'
            }`}
          >
            {index < actual ? <Check className="h-3.5 w-3.5" /> : index + 1}
          </span>
          <span className={index === actual ? 'text-foreground' : 'hidden text-muted-foreground sm:inline'}>
            {paso}
          </span>
          {index < PASOS.length - 1 ? <span aria-hidden className="h-px w-5 bg-border sm:w-8" /> : null}
        </li>
      ))}
    </ol>
  );
}

function Numero({ n }: { n: number }) {
  return (
    <span className="precio flex h-7 w-7 flex-shrink-0 items-center justify-center rounded-full bg-primary text-sm font-bold text-primary-foreground">
      {n}
    </span>
  );
}

export default function Apartado() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const lines = useCart();
  const { count, total } = cartTotals(lines);

  const [settings, setSettings] = useState<StoreSettings | null>(null);
  const [options, setOptions] = useState<OptionsResponse | null>(null);
  const [loadingOptions, setLoadingOptions] = useState(true);
  const [step, setStep] = useState<Step>('apartado');
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [touched, setTouched] = useState<Record<string, boolean>>({});
  const [pointId, setPointId] = useState<number | null>(null);
  const [dateIso, setDateIso] = useState('');
  const [slotStart, setSlotStart] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [stockWarnings, setStockWarnings] = useState<string[]>([]);

  useEffect(() => {
    setSeo({
      title: `Mi apartado — ${settings?.shop_name || SHOP_NAME_FALLBACK}`,
      description:
        'Revisa tus productos apartados, elige punto de entrega, fecha y horario. Sin pago en línea.',
    });
  }, [settings]);

  useEffect(() => {
    api<Bootstrap>('/api/v1/shop/bootstrap')
      .then((result) => setSettings(result.settings))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    api<OptionsResponse>('/api/v1/shop/delivery-options')
      .then((result) => {
        if (cancelled) return;
        setOptions(result);
        // Preselecciona el primer punto que sí tiene horarios.
        const first = result.delivery_points.find((p) => p.days.length > 0) || result.delivery_points[0];
        if (first) setPointId(first.id);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoadingOptions(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Revalidación de precios y stock contra el servidor al cargar el apartado guardado.
  useEffect(() => {
    const stored = cart.read();
    if (stored.length === 0) return;
    let cancelled = false;
    api<AvailabilityResponse>('/api/v1/shop/availability', 'POST', {
      items: stored.map((l) => ({ variant_id: l.variantId, quantity: l.quantity })),
    })
      .then((result) => {
        if (cancelled) return;
        const warnings: string[] = [];
        for (const line of result.lines) {
          if (!line.ok) {
            const original = stored.find((l) => l.variantId === line.variant_id);
            warnings.push(
              `${line.product_name || original?.name || 'Un producto'}: ${line.reason || 'ya no está disponible'}`,
            );
          }
        }
        cart.applyAvailability(result.lines);
        setStockWarnings(warnings);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const selectedPoint = useMemo(
    () => options?.delivery_points.find((p) => p.id === pointId) || null,
    [options, pointId],
  );

  const availableDays: DeliveryDay[] = useMemo(() => selectedPoint?.days ?? [], [selectedPoint]);

  const selectedDay = useMemo(
    () => availableDays.find((d) => d.date === dateIso) || null,
    [availableDays, dateIso],
  );

  const availableSlots: DeliverySlot[] = selectedDay?.slots || [];

  useEffect(() => {
    // Al cambiar de punto se reinicia la fecha y el horario.
    setDateIso('');
    setSlotStart('');
  }, [pointId]);

  useEffect(() => {
    setSlotStart('');
  }, [dateIso]);

  const whatsappDigits = form.whatsapp.replace(/\D/g, '');
  const emailValid = /^[^@\s]+@[^@\s]+\.[a-zA-Z]{2,}$/.test(form.email.trim());
  const nameValid = form.full_name.trim().length >= 3;
  const whatsappValid = whatsappDigits.length === 10;

  // En el orden en que aparecen en pantalla: al continuar se lleva a la clienta al primero que falte.
  const firstMissing = !pointId
    ? 'punto'
    : !dateIso
      ? 'fecha'
      : !slotStart
        ? 'horario'
        : !nameValid
          ? 'nombre'
          : !whatsappValid
            ? 'whatsapp'
            : !emailValid
              ? 'correo'
              : !form.privacy_accepted
                ? 'privacidad'
                : '';

  const handleContinueToReview = () => {
    setTouched({ full_name: true, whatsapp: true, email: true, privacy: true, slot: true });
    if (firstMissing) {
      const field = document.getElementById(firstMissing);
      field?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (field instanceof HTMLInputElement || field instanceof HTMLButtonElement) {
        field.focus({ preventScroll: true });
      }
      toast({
        title: 'Falta un dato para continuar',
        description: 'Te llevamos al campo que falta.',
        variant: 'destructive',
      });
      return;
    }
    setStep('revision');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const editar = () => {
    setStep('entrega');
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const handleSubmit = async () => {
    if (submitting) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      const created = await api<CreatedResponse>('/api/v1/shop/reservations', 'POST', {
        full_name: form.full_name.trim(),
        whatsapp: whatsappDigits,
        email: form.email.trim(),
        delivery_point_id: pointId,
        delivery_date: dateIso,
        slot_start: slotStart,
        notes: form.notes.trim(),
        privacy_accepted: form.privacy_accepted,
        fingerprint: fingerprint(),
        items: lines.map((l) => ({ variant_id: l.variantId, quantity: l.quantity })),
      });
      cart.clear();
      navigate(`/confirmacion#t=${encodeURIComponent(created.private_token)}&nueva=1`);
    } catch (e) {
      setSubmitError(apiError(e, 'No pudimos registrar tu apartado. Intenta de nuevo.'));
      setSubmitting(false);
    }
  };

  /* --------------------------- Apartado vacío --------------------------- */
  if (count === 0) {
    return (
      <ShopLayout settings={settings} hideCartBar>
        <h1 className="text-[1.75rem] sm:text-3xl">Mi apartado</h1>
        <div className="mt-4 rounded-2xl border border-border bg-card p-6 text-center">
          <h2 className="text-lg">Todavía no tienes productos apartados</h2>
          <p className="mx-auto mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            Explora el catálogo, elige tu tono o presentación favorita y aparta sin dar anticipo.
          </p>
          <Button asChild className="tap mt-4 rounded-full px-6">
            <Link to="/catalogo">Ver catálogo</Link>
          </Button>
        </div>
      </ShopLayout>
    );
  }

  /* ----------------------------- Revisión ------------------------------ */
  if (step === 'revision') {
    const editButton = (
      <button
        type="button"
        onClick={editar}
        className="tap -my-2 -mr-2 px-2 text-sm font-semibold text-primary underline-offset-4 hover:underline"
      >
        Editar
      </button>
    );
    return (
      <ShopLayout settings={settings} hideCartBar>
        <Pasos actual={1} />
        <button
          type="button"
          onClick={editar}
          className="tap -ml-2 mt-3 inline-flex items-center gap-1 pr-3 text-sm font-medium text-muted-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Volver a editar
        </button>

        <h1 className="mt-1 text-[1.75rem] sm:text-3xl">Revisa tu solicitud</h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Confirma que todo esté correcto. Al enviarla, apartamos tus productos y te mandamos tu folio por correo.
        </p>

        <div className="mt-5 grid gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
          <div className="space-y-4">
            <section className="rounded-2xl border border-border bg-card p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="flex items-center gap-2 text-base">
                  <MapPin className="h-4 w-4 text-primary" /> Entrega
                </h2>
                {editButton}
              </div>
              <p className="mt-2 text-sm font-semibold first-letter:uppercase">
                {fechaLarga(dateIso)} ·{' '}
                <span className="precio">
                  {availableSlots.find((s) => s.start_time === slotStart)?.label || slotStart}
                </span>
              </p>
              <p className="mt-1 text-sm font-medium">{selectedPoint?.name}</p>
              <p className="text-xs leading-relaxed text-muted-foreground">
                {selectedPoint?.reference || selectedPoint?.address}
              </p>
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-base">Tus datos</h2>
                {editButton}
              </div>
              <p className="mt-2 text-sm font-medium">{form.full_name}</p>
              <p className="precio text-sm text-muted-foreground">WhatsApp {whatsappDigits}</p>
              <p className="break-all text-sm text-muted-foreground">{form.email}</p>
              {form.notes ? (
                <p className="mt-2 whitespace-pre-line text-xs leading-relaxed text-muted-foreground">
                  Notas: {form.notes}
                </p>
              ) : null}
            </section>
          </div>

          <section className="rounded-2xl border border-border bg-card p-4 lg:sticky lg:top-20">
            <h2 className="text-base">
              Productos <span className="text-sm font-normal text-muted-foreground">({count})</span>
            </h2>
            <ul className="mt-2 divide-y divide-border">
              {lines.map((line) => (
                <li key={line.variantId} className="flex items-start gap-3 py-3">
                  <img
                    src={line.imageUrl}
                    alt=""
                    loading="lazy"
                    className="h-14 w-14 flex-shrink-0 rounded-lg bg-white object-cover"
                  />
                  <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold">{line.name}</p>
                    <p className="text-xs text-muted-foreground">{line.variantLabel}</p>
                    <p className="precio mt-1 text-xs text-muted-foreground">
                      {line.quantity} × {pesos(line.unitPrice)}
                    </p>
                  </div>
                  <span className="precio text-sm font-semibold">{pesos(line.unitPrice * line.quantity)}</span>
                </li>
              ))}
            </ul>
            <div className="mt-1 flex items-center justify-between border-t border-border pt-3">
              <span className="text-sm font-semibold">Total a pagar al recibir</span>
              <span className="precio text-2xl font-bold">{pesos(total)}</span>
            </div>
            <p className="mt-3 rounded-xl bg-accent/60 px-3 py-2.5 text-xs font-medium leading-relaxed text-accent-foreground">
              {AVISO_SIN_PAGO}
            </p>

            {submitError ? (
              <div
                role="alert"
                className="mt-4 flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-4"
              >
                <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
                <div>
                  <p className="text-sm font-semibold text-destructive">No pudimos enviar tu solicitud</p>
                  <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{submitError}</p>
                </div>
              </div>
            ) : null}

            <Button onClick={handleSubmit} disabled={submitting} className="tap mt-4 w-full rounded-full text-base">
              {submitting ? 'Registrando tu apartado…' : 'Enviar solicitud de apartado'}
            </Button>
            <p className="mt-2 text-center text-xs text-muted-foreground">
              Recibirás tu folio y el resumen por correo electrónico.
            </p>
          </section>
        </div>
      </ShopLayout>
    );
  }

  /* ------------------------ Apartado y entrega ------------------------- */
  const invalid = 'border-destructive ring-destructive';
  return (
    <ShopLayout settings={settings} hideCartBar>
      <Pasos actual={0} />
      <h1 className="mt-4 text-[1.75rem] sm:text-3xl">Mi apartado</h1>
      <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">
        Elige dónde y cuándo recibir tus productos. No necesitas crear una cuenta.
      </p>

      {stockWarnings.length > 0 ? (
        <div role="alert" className="mt-4 rounded-xl border border-destructive/40 bg-destructive/10 p-4">
          <p className="text-sm font-semibold text-destructive">Ajustamos tu apartado</p>
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
            {stockWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="mt-5 grid gap-5 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
        {/* Productos: arriba en celular; columna fija a la derecha en escritorio. */}
        <section
          aria-label="Productos apartados"
          className="rounded-2xl border border-border bg-card p-4 lg:sticky lg:top-20 lg:order-2"
        >
          <h2 className="text-base">
            Tus productos <span className="text-sm font-normal text-muted-foreground">({count})</span>
          </h2>
          <ul className="mt-1 divide-y divide-border">
            {lines.map((line) => (
              <li key={line.variantId} className="flex items-start gap-3 py-3">
                <Link to={`/producto/${line.slug}`} className="flex-shrink-0">
                  <img
                    src={line.imageUrl}
                    alt={line.name}
                    loading="lazy"
                    className="h-16 w-16 rounded-lg bg-white object-cover"
                  />
                </Link>
                <div className="min-w-0 flex-1">
                  <Link to={`/producto/${line.slug}`} className="text-sm font-semibold hover:underline">
                    {line.name}
                  </Link>
                  <p className="text-xs text-muted-foreground">{line.variantLabel}</p>
                  <div className="mt-2 flex items-center gap-2">
                    <div className="flex items-center gap-1 rounded-full border border-border">
                      <button
                        type="button"
                        aria-label={`Reducir cantidad de ${line.name}`}
                        onClick={() => cart.setQuantity(line.variantId, line.quantity - 1)}
                        className="h-9 w-9 rounded-full text-lg leading-none hover:bg-secondary"
                      >
                        −
                      </button>
                      <span className="precio w-6 text-center text-sm">{line.quantity}</span>
                      <button
                        type="button"
                        aria-label={`Aumentar cantidad de ${line.name}`}
                        disabled={line.quantity >= line.maxUnits}
                        onClick={() => cart.setQuantity(line.variantId, line.quantity + 1)}
                        className="h-9 w-9 rounded-full text-lg leading-none hover:bg-secondary disabled:opacity-40"
                      >
                        +
                      </button>
                    </div>
                    <button
                      type="button"
                      onClick={() => cart.remove(line.variantId)}
                      aria-label={`Quitar ${line.name} del apartado`}
                      className="tap flex items-center justify-center rounded-full text-muted-foreground hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                    <span className="precio ml-auto text-sm font-semibold">
                      {pesos(line.unitPrice * line.quantity)}
                    </span>
                  </div>
                </div>
              </li>
            ))}
          </ul>
          <div className="mt-1 flex items-center justify-between border-t border-border pt-3">
            <span className="text-sm font-semibold">Total a pagar al recibir</span>
            <span className="precio text-2xl font-bold">{pesos(total)}</span>
          </div>
          <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{AVISO_SIN_PAGO}</p>
          <Link
            to="/catalogo"
            className="tap mt-1 inline-flex items-center text-sm font-semibold text-primary underline-offset-4 hover:underline"
          >
            Agregar más productos
          </Link>
        </section>

        <div className="space-y-5 lg:order-1">
          {/* 1. Dónde y cuándo */}
          <section className="space-y-5 rounded-2xl border border-border bg-card p-4 sm:p-5">
            <h2 className="flex items-center gap-3 text-lg">
              <Numero n={1} /> ¿Dónde y cuándo te entregamos?
            </h2>

            <fieldset id="punto">
              <legend className="text-sm font-semibold">Punto de entrega</legend>
              {loadingOptions ? (
                <div className="mt-2 space-y-2">
                  <Skeleton className="h-16 rounded-xl" />
                  <Skeleton className="h-16 rounded-xl" />
                </div>
              ) : (options?.delivery_points.length || 0) === 0 ? (
                <p className="mt-2 rounded-xl border border-border bg-background p-3 text-sm text-muted-foreground">
                  No hay puntos de entrega disponibles en este momento. Escríbenos por WhatsApp para coordinar.
                </p>
              ) : (
                <div className="mt-2 grid gap-2 sm:grid-cols-2">
                  {options?.delivery_points.map((point) => {
                    const active = point.id === pointId;
                    const sinHorarios = point.days.length === 0;
                    return (
                      <button
                        key={point.id}
                        type="button"
                        disabled={sinHorarios}
                        aria-pressed={active}
                        onClick={() => setPointId(point.id)}
                        className={`flex items-start gap-2 rounded-xl border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${
                          active ? 'border-primary bg-accent ring-1 ring-primary' : 'border-border bg-background'
                        }`}
                      >
                        <MapPin
                          className={`mt-0.5 h-4 w-4 flex-shrink-0 ${active ? 'text-primary' : 'text-muted-foreground'}`}
                        />
                        <span className="min-w-0">
                          <span className="block text-sm font-semibold">{point.name}</span>
                          <span className="block text-xs leading-relaxed text-muted-foreground">
                            {point.reference || point.address}
                          </span>
                          {sinHorarios ? (
                            <span className="mt-1 block text-xs font-medium">Sin horarios disponibles por ahora</span>
                          ) : null}
                        </span>
                        {active ? <Check className="ml-auto mt-0.5 h-4 w-4 flex-shrink-0 text-primary" /> : null}
                      </button>
                    );
                  })}
                </div>
              )}
            </fieldset>

            {selectedPoint && availableDays.length > 0 ? (
              <fieldset id="fecha">
                <legend className="text-sm font-semibold">
                  Fecha
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    (próximos {options?.reservation_window_days || 7} días)
                  </span>
                </legend>
                <div className="chips mt-2 flex gap-2 overflow-x-auto pb-1">
                  {availableDays.map((day) => {
                    const active = day.date === dateIso;
                    const [, mes, dia] = day.date.split('-');
                    return (
                      <button
                        key={day.date}
                        type="button"
                        aria-pressed={active}
                        aria-label={fechaLarga(day.date)}
                        onClick={() => setDateIso(day.date)}
                        className={`flex min-h-[72px] min-w-[64px] flex-shrink-0 flex-col items-center justify-center rounded-xl border px-3 ${
                          active
                            ? 'border-primary bg-primary text-primary-foreground'
                            : 'border-border bg-background'
                        }`}
                      >
                        <span className="text-[11px] font-medium uppercase tracking-wide">{day.weekday_label}</span>
                        <span className="precio text-xl font-bold leading-tight">{Number(dia)}</span>
                        <span className="text-[11px]">{MESES[Number(mes) - 1]?.slice(0, 3)}</span>
                      </button>
                    );
                  })}
                </div>
                {touched.slot && !dateIso ? (
                  <p className="mt-1 text-xs text-destructive">Elige una fecha de entrega.</p>
                ) : null}
              </fieldset>
            ) : null}

            {dateIso && availableSlots.length > 0 ? (
              <fieldset id="horario">
                <legend className="text-sm font-semibold">Horario</legend>
                <div className="mt-2 flex flex-wrap gap-2">
                  {availableSlots.map((slot) => {
                    const active = slot.start_time === slotStart;
                    return (
                      <button
                        key={slot.id}
                        type="button"
                        aria-pressed={active}
                        onClick={() => setSlotStart(slot.start_time)}
                        className={`tap precio flex items-center gap-2 rounded-full border px-4 text-sm ${
                          active
                            ? 'border-primary bg-primary text-primary-foreground'
                            : 'border-border bg-background'
                        }`}
                      >
                        <Clock className="h-4 w-4" />
                        {slot.label}
                        {slot.remaining !== null && slot.remaining <= 2 ? (
                          <span className={`text-[11px] ${active ? '' : 'text-primary'}`}>
                            quedan {slot.remaining}
                          </span>
                        ) : null}
                      </button>
                    );
                  })}
                </div>
                {touched.slot && !slotStart ? (
                  <p className="mt-1 text-xs text-destructive">Elige un horario disponible.</p>
                ) : null}
              </fieldset>
            ) : null}
          </section>

          {/* 2. Datos de contacto */}
          <section className="space-y-4 rounded-2xl border border-border bg-card p-4 sm:p-5">
            <div>
              <h2 className="flex items-center gap-3 text-lg">
                <Numero n={2} /> Tus datos
              </h2>
              <p className="mt-1 text-sm text-muted-foreground">
                Solo para coordinar tu entrega y enviarte tu folio.
              </p>
            </div>

            <div>
              <Label htmlFor="nombre">Nombre completo</Label>
              <Input
                id="nombre"
                value={form.full_name}
                maxLength={120}
                autoComplete="name"
                placeholder="Nombre y apellido"
                onChange={(e) => setForm({ ...form, full_name: e.target.value })}
                onBlur={() => setTouched({ ...touched, full_name: true })}
                className={`tap mt-1 ${touched.full_name && !nameValid ? invalid : ''}`}
              />
              {touched.full_name && !nameValid ? (
                <p className="mt-1 text-xs text-destructive">Escribe tu nombre completo.</p>
              ) : null}
            </div>

            <div className="grid gap-4 sm:grid-cols-2">
              <div>
                <Label htmlFor="whatsapp">WhatsApp (10 dígitos)</Label>
                <Input
                  id="whatsapp"
                  type="tel"
                  inputMode="numeric"
                  autoComplete="tel-national"
                  placeholder="55 1234 5678"
                  value={form.whatsapp}
                  onChange={(e) => setForm({ ...form, whatsapp: e.target.value.replace(/[^\d\s-]/g, '') })}
                  onBlur={() => setTouched({ ...touched, whatsapp: true })}
                  className={`precio tap mt-1 ${touched.whatsapp && !whatsappValid ? invalid : ''}`}
                />
                {touched.whatsapp && !whatsappValid ? (
                  <p className="mt-1 text-xs text-destructive">
                    Necesitamos exactamente 10 dígitos, sin lada internacional.
                  </p>
                ) : null}
              </div>

              <div>
                <Label htmlFor="correo">Correo electrónico</Label>
                <Input
                  id="correo"
                  type="email"
                  autoComplete="email"
                  placeholder="tucorreo@ejemplo.com"
                  value={form.email}
                  onChange={(e) => setForm({ ...form, email: e.target.value })}
                  onBlur={() => setTouched({ ...touched, email: true })}
                  className={`tap mt-1 ${touched.email && !emailValid ? invalid : ''}`}
                />
                {touched.email && !emailValid ? (
                  <p className="mt-1 text-xs text-destructive">Escribe un correo válido para enviarte tu folio.</p>
                ) : null}
              </div>
            </div>

            <div>
              <Label htmlFor="notas">
                Notas para la entrega <span className="font-normal text-muted-foreground">(opcional)</span>
              </Label>
              <Textarea
                id="notas"
                value={form.notes}
                maxLength={400}
                rows={3}
                placeholder="Alguna referencia para encontrarnos o algo que debamos saber."
                aria-describedby="notas-ayuda"
                onChange={(e) => setForm({ ...form, notes: e.target.value })}
                className="mt-1"
              />
              <p id="notas-ayuda" className="precio mt-1 text-right text-xs text-muted-foreground">
                {form.notes.length}/400
              </p>
            </div>

            <div
              className={`flex items-start gap-3 rounded-xl border bg-background p-3 ${
                touched.privacy && !form.privacy_accepted ? 'border-destructive' : 'border-border'
              }`}
            >
              <Checkbox
                id="privacidad"
                checked={form.privacy_accepted}
                onCheckedChange={(value) => setForm({ ...form, privacy_accepted: value === true })}
                className="mt-0.5"
              />
              <Label htmlFor="privacidad" className="text-sm font-normal leading-relaxed">
                Acepto el{' '}
                <Link to="/aviso-de-privacidad" className="font-semibold text-primary underline-offset-4 hover:underline">
                  aviso de privacidad
                </Link>{' '}
                y que me contacten por WhatsApp o correo para coordinar mi entrega.
              </Label>
            </div>
            {touched.privacy && !form.privacy_accepted ? (
              <p className="-mt-2 text-xs text-destructive">
                Necesitamos tu consentimiento para poder coordinar la entrega.
              </p>
            ) : null}
          </section>

          <Button
            onClick={() => {
              setStep('entrega');
              handleContinueToReview();
            }}
            className="tap w-full rounded-full text-base"
          >
            Revisar mi solicitud
          </Button>
        </div>
      </div>
    </ShopLayout>
  );
}
