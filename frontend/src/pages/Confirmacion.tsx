import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Building2,
  CalendarPlus,
  Check,
  Clock,
  Copy,
  MapPin,
  MessageCircle,
  Navigation,
  Printer,
} from 'lucide-react';
import ShopLayout from '@/components/ShopLayout';
import { Button } from '@/components/ui/button';
import { ConfirmDialogHost, confirmAction } from '@/components/ui/confirm-dialog';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import {
  AVISO_SIN_PAGO,
  BankDetails,
  Reservation,
  api,
  apiError,
  fechaLarga,
  pesos,
  setSeo,
  whatsappLink,
} from '@/lib/shop';

interface ConfirmationResponse {
  reservation: Reservation;
  settings: {
    shop_name: string;
    logo_url: string;
    contact_whatsapp: string;
    delivery_instructions: string;
    reservation_policy: string;
  };
  bank_details: BankDetails;
}

const CERRADAS = ['cancelada', 'no_show', 'vencida', 'entregada'];

// Avance que ve la clienta; "confirmada" solo existe en apartados viejos y cuenta como recibida.
const SEGUIMIENTO = [
  { estados: ['recibida', 'confirmada'], label: 'Recibida' },
  { estados: ['preparando'], label: 'Preparando' },
  { estados: ['lista'], label: 'Lista' },
  { estados: ['entregada'], label: 'Entregada' },
];

function readPrivateFragment() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  return { token: params.get('t') || '', esNueva: params.get('nueva') === '1' };
}

// iPhone/iPad (los iPad nuevos se presentan como Mac con pantalla táctil).
const ES_IOS =
  /iPhone|iPad|iPod/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);

/** Lo que el mapa debe buscar: la dirección si la hay; sólo con el nombre ("Metro X") adivina. */
function lugar(reservation: Reservation) {
  return reservation.delivery_point_address || reservation.delivery_point_name;
}

/** Abre la app de mapas: Apple Maps en iPhone; en Android el enlace de Google abre su app. */
function mapaUrl(reservation: Reservation) {
  const q = encodeURIComponent(lugar(reservation));
  return ES_IOS ? `https://maps.apple.com/?q=${q}` : `https://www.google.com/maps/search/?api=1&query=${q}`;
}

/** Cita de entrega para el calendario (sin el enlace privado, que es secreto). */
function calendarioUrl(reservation: Reservation, shopName: string) {
  const titulo = `Recoger mi apartado ${reservation.folio} — ${shopName}`;
  const detalles = `Total a pagar al recibir: ${pesos(reservation.total_amount)}. ${AVISO_SIN_PAGO}`;
  const sitio = [reservation.delivery_point_name, lugar(reservation)].filter((v, i, all) => v && all.indexOf(v) === i).join(', ');
  // El iPhone abre un archivo .ics directo en su app Calendario; el servidor lo arma con los datos guardados.
  if (ES_IOS && reservation.calendar_url) return reservation.calendar_url;
  const dia = reservation.delivery_date.replace(/-/g, '');
  const hora = (value: string) => `${value.replace(':', '').slice(0, 4)}00`;
  const params = new URLSearchParams({
    action: 'TEMPLATE',
    text: titulo,
    dates: `${dia}T${hora(reservation.slot_start)}/${dia}T${hora(reservation.slot_end)}`,
    ctz: 'America/Mexico_City',
    location: sitio,
    details: detalles,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

export default function Confirmacion() {
  const [{ token, esNueva }] = useState(readPrivateFragment);
  const { toast } = useToast();

  const [data, setData] = useState<ConfirmationResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [cancelando, setCancelando] = useState(false);

  useEffect(() => {
    // La confirmación es privada: nunca debe indexarse.
    setSeo({
      title: 'Mi solicitud de apartado',
      description: 'Consulta privada de tu solicitud de apartado.',
      noindex: true,
    });
  }, []);

  useEffect(() => {
    if (!token) {
      setError('Este enlace no incluye el código de tu apartado.');
      setLoading(false);
      return;
    }
    let cancelled = false;
    api<ConfirmationResponse>('/api/v1/shop/confirmation', 'POST', { token })
      .then((result) => {
        if (!cancelled) setData(result);
      })
      .catch((e) => {
        if (!cancelled) setError(apiError(e, 'No encontramos esta reservación.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const reservation = data?.reservation || null;
  const cerrada = reservation ? CERRADAS.includes(reservation.status) : false;
  const avance = reservation ? SEGUIMIENTO.findIndex((paso) => paso.estados.includes(reservation.status)) : -1;

  const resumenTexto = useMemo(() => {
    if (!reservation) return '';
    const lineas = reservation.items.map(
      (item) =>
        `• ${item.product_name}${item.variant_label ? ` (${item.variant_label})` : ''} × ${item.quantity} — ${pesos(item.line_total)}`,
    );
    return [
      `Folio: ${reservation.folio}`,
      `Estado: ${reservation.status_label}`,
      '',
      'Productos apartados:',
      ...lineas,
      '',
      `Total a pagar al entregar: ${pesos(reservation.total_amount)}`,
      '',
      `Punto de entrega: ${reservation.delivery_point_name}`,
      reservation.delivery_point_reference ? `Referencia: ${reservation.delivery_point_reference}` : '',
      `Fecha: ${fechaLarga(reservation.delivery_date)}`,
      `Horario: ${reservation.slot_start} a ${reservation.slot_end}`,
      '',
      AVISO_SIN_PAGO,
    ]
      .filter(Boolean)
      .join('\n');
  }, [reservation]);

  const copiar = async (texto: string, mensaje: string) => {
    try {
      await navigator.clipboard.writeText(texto);
      toast({ title: mensaje });
    } catch {
      toast({ title: 'No pudimos copiar. Selecciona el texto manualmente.', variant: 'destructive' });
    }
  };

  const cancelarApartado = async () => {
    if (!data || !reservation) return;
    const ok = await confirmAction({
      title: '¿Cancelar tu apartado?',
      description: 'Tus productos quedarán libres para otras clientas. Si cambias de opinión, tendrás que apartarlos de nuevo.',
      confirmLabel: 'Sí, cancelar',
      destructive: true,
    });
    if (!ok) return;
    setCancelando(true);
    try {
      const result = await api<{ status: string; status_label: string }>(
        '/api/v1/shop/confirmation/cancel',
        'POST',
        { token },
      );
      setData({
        ...data,
        reservation: { ...reservation, ...result, cancel_reason: 'Cancelado por la clienta' },
      });
      toast({ title: 'Cancelamos tu apartado', description: 'La tienda ya puede ver la cancelación.' });
    } catch (e) {
      toast({ title: apiError(e, 'No pudimos cancelar tu apartado.'), variant: 'destructive' });
    } finally {
      setCancelando(false);
    }
  };

  if (loading) {
    return (
      <ShopLayout settings={null} hideCartBar>
        <Skeleton className="h-8 w-2/3" />
        <Skeleton className="mt-3 h-5 w-1/3" />
        <Skeleton className="mt-5 h-48 w-full rounded-2xl" />
        <Skeleton className="mt-4 h-32 w-full rounded-2xl" />
      </ShopLayout>
    );
  }

  if (error || !reservation) {
    return (
      <ShopLayout settings={null} hideCartBar>
        <div className="rounded-2xl border border-border bg-card p-6">
          <h1 className="text-xl">No encontramos esta reservación</h1>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            {error || 'El enlace puede estar incompleto o haber sido reemplazado.'} Revisa el correo que
            te enviamos y abre el enlace completo, o escríbenos por WhatsApp con tu folio.
          </p>
          <Button asChild className="tap mt-4 rounded-full">
            <Link to="/">Volver al inicio</Link>
          </Button>
        </div>
      </ShopLayout>
    );
  }

  const exito = esNueva && !cerrada;
  const FolioTag = exito ? 'h2' : 'h1';
  const outline = 'tap rounded-full !bg-transparent hover:!bg-transparent';

  return (
    <ShopLayout settings={null} hideCartBar>
      <ConfirmDialogHost />
      {exito ? (
        <div className="no-imprimir mb-6 rounded-3xl bg-accent/60 px-5 py-7 text-center sm:py-9">
          <span className="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-primary text-primary-foreground animate-in zoom-in-50 duration-500">
            <Check className="h-7 w-7" strokeWidth={3} />
          </span>
          <h1 className="mt-4 text-2xl sm:text-3xl">¡Listo! Apartamos tus productos</h1>
          <p className="mx-auto mt-2 max-w-md text-sm leading-relaxed text-muted-foreground">
            Te enviamos este resumen a tu correo con tu enlace privado. Si no lo ves, revisa la carpeta de spam.
          </p>
        </div>
      ) : null}

      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">Folio de tu apartado</p>
          <FolioTag className="precio mt-1 text-[1.75rem] font-bold sm:text-3xl">{reservation.folio}</FolioTag>
        </div>
        <span className="text-sm text-muted-foreground">
          {reservation.item_count === 1 ? '1 artículo' : `${reservation.item_count} artículos`}
        </span>
      </header>

      {avance >= 0 ? (
        <ol aria-label="Estado de tu apartado" className="mt-4 grid grid-cols-4 gap-1.5">
          {SEGUIMIENTO.map((paso, index) => (
            <li key={paso.label} aria-current={index === avance ? 'step' : undefined}>
              <span className={`block h-1.5 rounded-full ${index <= avance ? 'bg-primary' : 'bg-secondary'}`} />
              <span
                className={`mt-1.5 block text-[11px] sm:text-xs ${
                  index === avance ? 'font-semibold text-foreground' : 'text-muted-foreground'
                }`}
              >
                {paso.label}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="mt-4 flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm leading-relaxed">
          <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
          <span>
            <strong>{reservation.status_label}.</strong>{' '}
            <span className="text-muted-foreground">{reservation.cancel_reason}</span>
          </span>
        </p>
      )}

      <div className="mt-6 grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_380px] lg:items-start">
        <div className="space-y-4">
          {/* La cita es lo que más necesita la clienta: va primero y con acciones. */}
          <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
            <h2 className="text-base">Tu entrega</h2>
            <div className="mt-3 space-y-3">
              <p className="flex items-start gap-3">
                <Clock className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary" />
                <span>
                  <span className="block font-semibold first-letter:uppercase">
                    {fechaLarga(reservation.delivery_date)}
                  </span>
                  <span className="precio block text-sm text-muted-foreground">
                    {reservation.slot_start} a {reservation.slot_end}
                  </span>
                </span>
              </p>
              <p className="flex items-start gap-3">
                <MapPin className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary" />
                <span>
                  <span className="block font-semibold">{reservation.delivery_point_name}</span>
                  {reservation.delivery_point_reference ? (
                    <span className="block text-sm leading-relaxed text-muted-foreground">
                      {reservation.delivery_point_reference}
                    </span>
                  ) : null}
                </span>
              </p>
            </div>
            {!cerrada ? (
              <div className="no-imprimir mt-4 flex flex-wrap gap-2">
                {reservation.slot_start && reservation.slot_end ? (
                  <Button asChild variant="outline" className={outline}>
                    <a
                      href={calendarioUrl(reservation, data.settings.shop_name)}
                      target={ES_IOS ? undefined : '_blank'}
                      rel="noreferrer"
                    >
                      <CalendarPlus className="mr-2 h-4 w-4" /> Agregar a mi calendario
                    </a>
                  </Button>
                ) : null}
                <Button asChild variant="outline" className={outline}>
                  <a
                    href={mapaUrl(reservation)}
                    target="_blank"
                    rel="noreferrer"
                  >
                    <Navigation className="mr-2 h-4 w-4" /> Cómo llegar
                  </a>
                </Button>
              </div>
            ) : null}
            {data.settings.delivery_instructions ? (
              <div className="mt-4 rounded-xl bg-secondary/60 p-3">
                <p className="text-sm font-semibold">Instrucciones para la entrega</p>
                <p className="mt-1 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {data.settings.delivery_instructions}
                </p>
              </div>
            ) : null}
          </section>

          {/* Datos bancarios: entregados solo por API con token válido */}
          {!cerrada && (data.bank_details.clabe || data.bank_details.account_number) ? (
            <section className="rounded-2xl border border-border bg-card p-4 sm:p-5">
              <h2 className="flex items-center gap-2 text-base">
                <Building2 className="h-4 w-4 text-primary" /> Datos para tu transferencia
              </h2>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                Usa estos datos <strong className="text-foreground">solo al momento de la entrega</strong>,
                frente a la persona que te entrega tus productos.
              </p>
              <dl className="mt-3 space-y-2 text-sm">
                {data.bank_details.bank_name ? (
                  <div className="flex flex-wrap justify-between gap-2 border-b border-border pb-2">
                    <dt className="text-muted-foreground">Banco</dt>
                    <dd className="font-medium">{data.bank_details.bank_name}</dd>
                  </div>
                ) : null}
                {data.bank_details.account_holder ? (
                  <div className="flex flex-wrap justify-between gap-2 border-b border-border pb-2">
                    <dt className="text-muted-foreground">Titular</dt>
                    <dd className="font-medium">{data.bank_details.account_holder}</dd>
                  </div>
                ) : null}
                {data.bank_details.clabe ? (
                  <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border pb-2">
                    <dt className="text-muted-foreground">CLABE</dt>
                    <dd className="flex items-center gap-2">
                      <span className="precio font-medium">{data.bank_details.clabe}</span>
                      <button
                        type="button"
                        onClick={() => copiar(data.bank_details.clabe, 'CLABE copiada')}
                        aria-label="Copiar CLABE"
                        className="no-imprimir flex h-9 w-9 items-center justify-center rounded-full border border-border hover:bg-secondary"
                      >
                        <Copy className="h-4 w-4" />
                      </button>
                    </dd>
                  </div>
                ) : null}
                {data.bank_details.account_number ? (
                  <div className="flex flex-wrap justify-between gap-2">
                    <dt className="text-muted-foreground">Cuenta</dt>
                    <dd className="precio font-medium">{data.bank_details.account_number}</dd>
                  </div>
                ) : null}
              </dl>
              {data.bank_details.transfer_instructions ? (
                <p className="mt-3 whitespace-pre-line text-xs leading-relaxed text-muted-foreground">
                  {data.bank_details.transfer_instructions}
                </p>
              ) : null}
            </section>
          ) : null}
        </div>

        <section className="rounded-2xl border border-border bg-card p-4 sm:p-5 lg:sticky lg:top-20">
          <h2 className="text-base">Productos apartados</h2>
          <ul className="mt-1 divide-y divide-border">
            {reservation.items.map((item) => (
              <li
                key={`${item.product_name}-${item.variant_label}-${item.quantity}`}
                className="flex items-start gap-3 py-3"
              >
                {item.image_url ? (
                  <img
                    src={item.image_url}
                    alt=""
                    loading="lazy"
                    className="h-14 w-14 flex-shrink-0 rounded-lg bg-white object-cover"
                  />
                ) : null}
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-semibold">{item.product_name}</p>
                  {item.variant_label ? (
                    <p className="text-xs text-muted-foreground">{item.variant_label}</p>
                  ) : null}
                  <p className="precio mt-1 text-xs text-muted-foreground">
                    {item.quantity} × {pesos(item.unit_price)}
                  </p>
                </div>
                <span className="precio text-sm font-semibold">{pesos(item.line_total)}</span>
              </li>
            ))}
          </ul>
          <div className="mt-1 flex items-center justify-between border-t border-border pt-3">
            <span className="text-sm font-semibold">Total a pagar al recibir</span>
            <span className="precio text-2xl font-bold">{pesos(reservation.total_amount)}</span>
          </div>
          <p className="mt-3 rounded-xl bg-accent/60 px-3 py-2.5 text-xs font-medium leading-relaxed text-accent-foreground">
            {AVISO_SIN_PAGO}
          </p>
        </section>
      </div>

      <div className="no-imprimir mt-6 flex flex-wrap gap-2">
        {data.settings.contact_whatsapp ? (
          <Button asChild className="tap rounded-full">
            <a
              href={whatsappLink(
                data.settings.contact_whatsapp,
                `Hola, tengo una duda sobre mi apartado ${reservation.folio}.`,
              )}
              target="_blank"
              rel="noreferrer"
            >
              <MessageCircle className="mr-2 h-4 w-4" /> Escribir por WhatsApp
            </a>
          </Button>
        ) : null}
        <Button type="button" onClick={() => copiar(resumenTexto, 'Resumen copiado')} variant="outline" className={outline}>
          <Copy className="mr-2 h-4 w-4" /> Copiar resumen
        </Button>
        <Button type="button" onClick={() => window.print()} variant="outline" className={outline}>
          <Printer className="mr-2 h-4 w-4" /> Imprimir o guardar PDF
        </Button>
      </div>

      <div className="no-imprimir mt-6 divide-y divide-border rounded-2xl border border-border bg-card">
        <div className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div className="max-w-prose">
            <p className="text-sm font-semibold">Tu enlace privado</p>
            <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
              Es único y personal: guárdalo para consultar tu apartado cuando quieras, sin crear cuenta.
            </p>
          </div>
          <Button
            type="button"
            variant="outline"
            className={outline}
            onClick={() => copiar(window.location.href, 'Enlace privado copiado')}
          >
            Copiar enlace
          </Button>
        </div>
        {!cerrada ? (
          <div className="flex flex-wrap items-center justify-between gap-3 p-4">
            <div className="max-w-prose">
              <p className="text-sm font-semibold">¿Ya no puedes asistir?</p>
              <p className="mt-0.5 text-xs leading-relaxed text-muted-foreground">
                Cancela para liberar los productos. La tienda verá la cancelación.
              </p>
            </div>
            <Button
              type="button"
              variant="ghost"
              disabled={cancelando}
              className="tap rounded-full text-destructive hover:bg-destructive/10 hover:text-destructive"
              onClick={cancelarApartado}
            >
              {cancelando ? 'Cancelando…' : 'Cancelar mi apartado'}
            </Button>
          </div>
        ) : null}
      </div>

      <div className="no-imprimir mt-6 text-center">
        <Link to="/catalogo" className="text-sm font-semibold text-primary underline-offset-4 hover:underline">
          Seguir viendo el catálogo
        </Link>
      </div>
    </ShopLayout>
  );
}
