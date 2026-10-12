import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, CalendarDays, Check, ChevronLeft, MapPin, Trash2 } from 'lucide-react';
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
  StoreSettings,
  api,
  apiError,
  cart,
  cartTotals,
  fechaLarga,
  fingerprint,
  pesos,
  setSeo,
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
      title: `Mi apartado — ${settings?.shop_name || 'Nébula Beauty MX'}`,
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
        if (result.delivery_points.length > 0) {
          setPointId(result.delivery_points[0].id);
        }
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

  const contactComplete =
    nameValid && whatsappValid && emailValid && form.privacy_accepted && Boolean(pointId) && Boolean(dateIso) && Boolean(slotStart);

  const handleContinueToReview = () => {
    setTouched({ full_name: true, whatsapp: true, email: true, privacy: true, slot: true });
    if (!contactComplete) {
      toast({
        title: 'Faltan datos para continuar',
        description: 'Revisa los campos marcados y elige punto, fecha y horario.',
        variant: 'destructive',
      });
      return;
    }
    setStep('revision');
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
    return (
      <ShopLayout settings={settings} hideCartBar>
        <button
          type="button"
          onClick={() => setStep('entrega')}
          className="tap -ml-2 inline-flex items-center gap-1 pr-3 text-sm font-medium text-muted-foreground"
        >
          <ChevronLeft className="h-4 w-4" /> Volver a editar
        </button>

        <h1 className="mt-2 text-[1.75rem] sm:text-3xl">Revisa tu solicitud</h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">
          Confirma que todo esté correcto antes de enviar tu solicitud de apartado.
        </p>

        <section className="mt-5 rounded-2xl border border-border bg-card p-4">
          <h2 className="text-base">Productos</h2>
          <ul className="mt-3 divide-y divide-border">
            {lines.map((line) => (
              <li key={line.variantId} className="flex items-start gap-3 py-3">
                <img
                  src={line.imageUrl}
                  alt={line.name}
                  loading="lazy"
                  className="h-14 w-14 flex-shrink-0 rounded-lg object-cover"
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{line.name}</p>
                  <p className="text-xs text-muted-foreground">{line.variantLabel}</p>
                  <p className="precio mt-1 text-xs text-muted-foreground">
                    {line.quantity} × {pesos(line.unitPrice)}
                  </p>
                </div>
                <span className="precio text-sm font-semibold">
                  {pesos(line.unitPrice * line.quantity)}
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
            <span className="text-sm font-semibold">Total a pagar al entregar</span>
            <span className="precio text-2xl font-bold text-primary">{pesos(total)}</span>
          </div>
        </section>

        <section className="mt-4 grid gap-4 sm:grid-cols-2">
          <div className="rounded-2xl border border-border bg-card p-4">
            <h2 className="text-base">Entrega</h2>
            <p className="mt-2 text-sm font-medium">{selectedPoint?.name}</p>
            <p className="text-xs leading-relaxed text-muted-foreground">
              {selectedPoint?.reference || selectedPoint?.address}
            </p>
            <p className="mt-2 text-sm">{fechaLarga(dateIso)}</p>
            <p className="text-sm text-muted-foreground">
              {availableSlots.find((s) => s.start_time === slotStart)?.label || slotStart}
            </p>
          </div>
          <div className="rounded-2xl border border-border bg-card p-4">
            <h2 className="text-base">Tus datos</h2>
            <p className="mt-2 text-sm font-medium">{form.full_name}</p>
            <p className="precio text-sm text-muted-foreground">WhatsApp {whatsappDigits}</p>
            <p className="break-all text-sm text-muted-foreground">{form.email}</p>
            {form.notes ? (
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">Notas: {form.notes}</p>
            ) : null}
          </div>
        </section>

        <p className="mt-4 rounded-xl border border-primary/30 bg-accent px-4 py-3 text-sm font-medium leading-relaxed text-accent-foreground">
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

        <Button
          onClick={handleSubmit}
          disabled={submitting}
          className="tap mt-5 w-full rounded-full text-base"
        >
          {submitting ? 'Registrando tu apartado…' : 'Enviar solicitud de apartado'}
        </Button>
        <p className="mt-2 text-center text-xs text-muted-foreground">
          Recibirás tu folio y el resumen por correo electrónico.
        </p>
      </ShopLayout>
    );
  }

  /* ------------------------ Apartado y entrega ------------------------- */
  return (
    <ShopLayout settings={settings} hideCartBar>
      <h1 className="text-[1.75rem] sm:text-3xl">Mi apartado</h1>
      <p className="mt-1 text-sm text-muted-foreground">
        {count === 1 ? '1 artículo apartado' : `${count} artículos apartados`}
      </p>

      {stockWarnings.length > 0 ? (
        <div
          role="alert"
          className="mt-4 rounded-xl border border-destructive/40 bg-destructive/10 p-4"
        >
          <p className="text-sm font-semibold text-destructive">Ajustamos tu apartado</p>
          <ul className="mt-1 space-y-1 text-sm text-muted-foreground">
            {stockWarnings.map((warning) => (
              <li key={warning}>{warning}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {/* Lista editable */}
      <section className="mt-4 rounded-2xl border border-border bg-card p-4">
        <ul className="divide-y divide-border">
          {lines.map((line) => (
            <li key={line.variantId} className="flex items-start gap-3 py-3 first:pt-0">
              <Link to={`/producto/${line.slug}`} className="flex-shrink-0">
                <img
                  src={line.imageUrl}
                  alt={line.name}
                  loading="lazy"
                  className="h-16 w-16 rounded-lg object-cover"
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
        <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
          <span className="text-sm font-semibold">Total a pagar al entregar</span>
          <span className="precio text-2xl font-bold text-primary">{pesos(total)}</span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{AVISO_SIN_PAGO}</p>
      </section>

      {/* Formulario de entrega */}
      <section className="mt-6" id="entrega">
        <h2>Datos de entrega</h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          No necesitas crear una cuenta. Solo pedimos lo necesario para coordinar tu entrega.
        </p>

        <div className="mt-4 space-y-4 rounded-2xl border border-border bg-card p-4">
          <div>
            <Label htmlFor="nombre">Nombre completo</Label>
            <Input
              id="nombre"
              value={form.full_name}
              autoComplete="name"
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              onBlur={() => setTouched({ ...touched, full_name: true })}
              className={`tap mt-1 ${touched.full_name && !nameValid ? 'border-destructive ring-destructive' : ''}`}
            />
            {touched.full_name && !nameValid ? (
              <p className="mt-1 text-xs text-destructive">Escribe tu nombre completo.</p>
            ) : null}
          </div>

          <div>
            <Label htmlFor="whatsapp">WhatsApp a 10 dígitos</Label>
            <Input
              id="whatsapp"
              inputMode="numeric"
              autoComplete="tel-national"
              placeholder="5512345678"
              value={form.whatsapp}
              onChange={(e) => setForm({ ...form, whatsapp: e.target.value.replace(/[^\d\s-]/g, '') })}
              onBlur={() => setTouched({ ...touched, whatsapp: true })}
              className={`precio tap mt-1 ${touched.whatsapp && !whatsappValid ? 'border-destructive ring-destructive' : ''}`}
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
              className={`tap mt-1 ${touched.email && !emailValid ? 'border-destructive ring-destructive' : ''}`}
            />
            {touched.email && !emailValid ? (
              <p className="mt-1 text-xs text-destructive">Escribe un correo válido para enviarte tu folio.</p>
            ) : null}
          </div>

          {/* Punto de entrega */}
          <fieldset>
            <legend className="text-sm font-medium">Punto de entrega</legend>
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
              <div className="mt-2 grid gap-2">
                {options?.delivery_points.map((point) => {
                  const active = point.id === pointId;
                  return (
                    <button
                      key={point.id}
                      type="button"
                      onClick={() => setPointId(point.id)}
                      className={`flex items-start gap-2 rounded-xl border p-3 text-left transition-colors ${
                        active ? 'border-primary bg-accent' : 'border-border bg-background'
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
                        {point.days.length === 0 ? (
                          <span className="mt-1 block text-xs text-destructive">
                            Sin horarios disponibles esta semana
                          </span>
                        ) : null}
                      </span>
                      {active ? <Check className="ml-auto mt-0.5 h-4 w-4 text-primary" /> : null}
                    </button>
                  );
                })}
              </div>
            )}
          </fieldset>

          {/* Fecha */}
          {selectedPoint && availableDays.length > 0 ? (
            <fieldset>
              <legend className="text-sm font-medium">
                Fecha de entrega
                <span className="ml-1 text-xs font-normal text-muted-foreground">
                  (próximos {options?.reservation_window_days || 7} días)
                </span>
              </legend>
              <div className="chips mt-2 flex gap-2 overflow-x-auto pb-1">
                {availableDays.map((day) => {
                  const active = day.date === dateIso;
                  const [, , dayNumber] = day.date.split('-');
                  return (
                    <button
                      key={day.date}
                      type="button"
                      onClick={() => setDateIso(day.date)}
                      className={`flex min-h-[62px] flex-shrink-0 flex-col items-center justify-center rounded-xl border px-4 ${
                        active ? 'border-primary bg-accent text-accent-foreground' : 'border-border bg-background'
                      }`}
                    >
                      <span className="text-[11px] uppercase tracking-wide">{day.weekday_label}</span>
                      <span className="precio text-lg font-bold">{Number(dayNumber)}</span>
                    </button>
                  );
                })}
              </div>
            </fieldset>
          ) : null}

          {/* Horario */}
          {dateIso && availableSlots.length > 0 ? (
            <fieldset>
              <legend className="text-sm font-medium">Horario</legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {availableSlots.map((slot) => {
                  const active = slot.start_time === slotStart;
                  return (
                    <button
                      key={slot.id}
                      type="button"
                      onClick={() => setSlotStart(slot.start_time)}
                      className={`tap precio flex items-center gap-2 rounded-full border px-4 text-sm ${
                        active ? 'border-primary bg-accent text-accent-foreground' : 'border-border bg-background'
                      }`}
                    >
                      <CalendarDays className="h-4 w-4" />
                      {slot.label}
                      {slot.remaining !== null && slot.remaining <= 2 ? (
                        <span className="text-[11px] text-primary">quedan {slot.remaining}</span>
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

          <div>
            <Label htmlFor="notas">Notas para la entrega (opcional)</Label>
            <Textarea
              id="notas"
              value={form.notes}
              rows={3}
              placeholder="Alguna referencia útil para encontrarnos o pedir algo especial."
              onChange={(e) => setForm({ ...form, notes: e.target.value })}
              className="mt-1"
            />
          </div>

          <div className="flex items-start gap-3 rounded-xl border border-border bg-background p-3">
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
            <p className="text-xs text-destructive">
              Necesitamos tu consentimiento para poder coordinar la entrega.
            </p>
          ) : null}
        </div>

        <Button
          onClick={() => {
            setStep('entrega');
            handleContinueToReview();
          }}
          className="tap mt-4 w-full rounded-full text-base"
        >
          Revisar mi solicitud
        </Button>
      </section>
    </ShopLayout>
  );
}
