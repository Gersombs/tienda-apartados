import { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import {
  AlertTriangle,
  Building2,
  CalendarDays,
  CheckCircle2,
  Copy,
  MapPin,
  MessageCircle,
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

const STATUS_TONE: Record<string, string> = {
  recibida: 'bg-secondary text-secondary-foreground',
  confirmada: 'bg-accent text-accent-foreground',
  preparando: 'bg-accent text-accent-foreground',
  lista: 'bg-primary text-primary-foreground',
  entregada: 'bg-foreground text-background',
  cancelada: 'bg-destructive/15 text-destructive',
  no_show: 'bg-destructive/15 text-destructive',
  vencida: 'bg-destructive/15 text-destructive',
};

const CERRADAS = ['cancelada', 'no_show', 'vencida', 'entregada'];

function readPrivateFragment() {
  const params = new URLSearchParams(window.location.hash.replace(/^#/, ''));
  return { token: params.get('t') || '', esNueva: params.get('nueva') === '1' };
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

  return (
    <ShopLayout settings={null} hideCartBar>
      <ConfirmDialogHost />
      {esNueva ? (
        <div className="no-imprimir flex items-start gap-3 rounded-2xl border border-primary/30 bg-accent p-4">
          <CheckCircle2 className="mt-0.5 h-5 w-5 flex-shrink-0 text-primary" />
          <div>
            <p className="text-sm font-semibold text-accent-foreground">
              Recibimos tu solicitud de apartado
            </p>
            <p className="mt-1 text-sm leading-relaxed text-accent-foreground/90">
              Te enviamos este resumen por correo. Guarda este enlace privado para consultar tu apartado
              cuando quieras.
            </p>
          </div>
        </div>
      ) : null}

      <header className="mt-5">
        <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">
          Solicitud de apartado
        </p>
        <h1 className="precio mt-1 text-[1.75rem] sm:text-3xl">{reservation.folio}</h1>
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <span
            className={`rounded-full px-3 py-1 text-sm font-semibold ${
              STATUS_TONE[reservation.status] || STATUS_TONE.recibida
            }`}
          >
            {reservation.status_label}
          </span>
          <span className="text-sm text-muted-foreground">
            {reservation.item_count === 1 ? '1 artículo' : `${reservation.item_count} artículos`}
          </span>
        </div>
        {cerrada && reservation.cancel_reason ? (
          <p className="mt-3 flex items-start gap-2 rounded-xl border border-destructive/40 bg-destructive/10 p-3 text-sm leading-relaxed text-muted-foreground">
            <AlertTriangle className="mt-0.5 h-4 w-4 flex-shrink-0 text-destructive" />
            {reservation.cancel_reason}
          </p>
        ) : null}
      </header>

      <section className="mt-5 rounded-2xl border border-border bg-card p-4">
        <h2 className="text-base">Productos apartados</h2>
        <ul className="mt-3 divide-y divide-border">
          {reservation.items.map((item) => (
            <li
              key={`${item.product_name}-${item.variant_label}-${item.quantity}`}
              className="flex items-start gap-3 py-3"
            >
              {item.image_url ? (
                <img
                  src={item.image_url}
                  alt={item.product_name}
                  loading="lazy"
                  className="h-14 w-14 flex-shrink-0 rounded-lg object-cover"
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
        <div className="mt-3 flex items-center justify-between border-t border-border pt-3">
          <span className="text-sm font-semibold">Total a pagar al entregar</span>
          <span className="precio text-2xl font-bold text-primary">
            {pesos(reservation.total_amount)}
          </span>
        </div>
      </section>

      <section className="mt-4 grid gap-4 sm:grid-cols-2">
        <div className="rounded-2xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base">
            <MapPin className="h-4 w-4 text-primary" /> Punto de entrega
          </h2>
          <p className="mt-2 text-sm font-medium">{reservation.delivery_point_name}</p>
          {reservation.delivery_point_reference ? (
            <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
              {reservation.delivery_point_reference}
            </p>
          ) : null}
        </div>
        <div className="rounded-2xl border border-border bg-card p-4">
          <h2 className="flex items-center gap-2 text-base">
            <CalendarDays className="h-4 w-4 text-primary" /> Fecha y horario
          </h2>
          <p className="mt-2 text-sm font-medium first-letter:uppercase">{fechaLarga(reservation.delivery_date)}</p>
          <p className="precio mt-1 text-sm text-muted-foreground">
            {reservation.slot_start} a {reservation.slot_end}
          </p>
        </div>
      </section>

      {/* Datos bancarios: entregados solo por API con token válido */}
      {!cerrada && (data.bank_details.clabe || data.bank_details.account_number) ? (
        <section className="mt-4 rounded-2xl border border-border bg-card p-4">
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

      {data.settings.delivery_instructions ? (
        <section className="mt-4 rounded-2xl border border-border bg-secondary/60 p-4">
          <h2 className="text-base">Instrucciones para la entrega</h2>
          <p className="mt-2 whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
            {data.settings.delivery_instructions}
          </p>
        </section>
      ) : null}

      <p className="mt-4 rounded-xl border border-primary/30 bg-accent px-4 py-3 text-sm font-medium leading-relaxed text-accent-foreground">
        {AVISO_SIN_PAGO}
      </p>

      <div className="no-imprimir mt-5 flex flex-wrap gap-2">
        <Button
          type="button"
          onClick={() => copiar(resumenTexto, 'Resumen copiado')}
          variant="outline"
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
        >
          <Copy className="mr-2 h-4 w-4" /> Copiar resumen
        </Button>
        <Button
          type="button"
          onClick={() => window.print()}
          variant="outline"
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
        >
          <Printer className="mr-2 h-4 w-4" /> Imprimir o guardar como PDF
        </Button>
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
      </div>

      <div className="no-imprimir mt-4 rounded-xl border border-border bg-card p-4">
        <p className="text-sm font-semibold">Tu enlace privado</p>
        <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
          Este enlace es único y personal. Guárdalo para consultar el estado de tu apartado sin necesidad
          de cuenta.
        </p>
        <Button
          type="button"
          variant="ghost"
          className="tap mt-2 px-0 text-primary"
          onClick={() => copiar(window.location.href, 'Enlace privado copiado')}
        >
          Copiar mi enlace privado
        </Button>
      </div>

      {!cerrada ? (
        <div className="no-imprimir mt-4 rounded-xl border border-border bg-card p-4">
          <p className="text-sm font-semibold">¿Ya no puedes asistir?</p>
          <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
            Cancela tu apartado para liberar los productos. La tienda verá la cancelación.
          </p>
          <Button
            type="button"
            variant="ghost"
            disabled={cancelando}
            className="tap mt-2 px-0 text-destructive"
            onClick={cancelarApartado}
          >
            {cancelando ? 'Cancelando…' : 'Cancelar mi apartado'}
          </Button>
        </div>
      ) : null}

      <div className="no-imprimir mt-5">
        <Button asChild variant="outline" className="tap rounded-full !bg-transparent hover:!bg-transparent">
          <Link to="/catalogo">Seguir viendo el catálogo</Link>
        </Button>
      </div>
    </ShopLayout>
  );
}
