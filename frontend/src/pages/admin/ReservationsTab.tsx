import { useCallback, useEffect, useState } from 'react';
import { Copy, Download, Link2, Mail, RefreshCw, Search, Unlink } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { confirmAction } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Reservation, api, apiError, downloadApi, fechaCorta, fechaHora, pesos } from '@/lib/shop';
import { ACTIVE_RESERVATION_STATUSES, EMAIL_STATUS_TONE, LINK_EMAIL_TEMPLATES, MANUAL_EMAIL_LABELS, TEMPLATE_LABELS } from './types';
import type { NotificationRow, ReservationDetail, ReservationRow, StatusOption, ToastFn } from './types';

/* ------------------------- Reservaciones ------------------------- */

export function ReservationsTab({ toast }: { toast: ToastFn }) {
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
    const ok = await confirmAction({
      title: '¿Enviar un enlace nuevo a la clienta?',
      description: 'Le llegará por correo. El enlace que tenía antes dejará de funcionar.',
      confirmLabel: 'Enviar enlace',
    });
    if (!ok) {
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
        title: result.email_sent ? 'Enlace enviado a la clienta' : 'Copia el enlace nuevo',
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
    const ok = await confirmAction({
      title: '¿Desactivar el enlace de la clienta?',
      description: 'Ya no podrá ver su apartado con ese enlace. Después puedes enviarle uno nuevo.',
      confirmLabel: 'Desactivar',
      destructive: true,
    });
    if (!ok) {
      return;
    }
    setWorking(true);
    try {
      await api(`/api/v1/crm/reservations/${selected}/revoke-confirmation-token`, 'POST');
      setPrivateLink('');
      setLinkDeliveryStatus('El enlace de la clienta quedó desactivado.');
      toast({ title: 'Enlace desactivado' });
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
                <p className="mt-3 whitespace-pre-line rounded-lg bg-secondary p-3 text-xs leading-relaxed">
                  Nota de la clienta: {detail.reservation.customer_notes}
                </p>
              ) : null}
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="text-sm font-semibold">Cambiar estado</h3>
              <p className="mt-1 text-xs text-muted-foreground">
                Sólo «Cancelada» le avisa a la clienta por correo; los demás estados son para tu control.
              </p>
              <Label htmlFor="estado-nota" className="mt-2 block text-xs text-muted-foreground">
                Motivo o nota del cambio (opcional)
              </Label>
              <Textarea
                id="estado-nota"
                value={statusNote}
                onChange={(e) => setStatusNote(e.target.value)}
                rows={2}
                className="mt-1 text-sm"
              />
              <div className="mt-2 flex flex-wrap gap-2">
                {detail.statuses.length === 0 ? (
                  <p className="text-xs text-muted-foreground">Este apartado ya terminó; no tiene más cambios.</p>
                ) : null}
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
              <Label htmlFor="nota-interna" className="mt-2 block text-xs text-muted-foreground">
                Sólo la ve el equipo, nunca la clienta.
              </Label>
              <Textarea
                id="nota-interna"
                value={note}
                onChange={(e) => setNote(e.target.value)}
                rows={3}
                className="mt-1 text-sm"
              />
              <Button size="sm" className="tap mt-2 rounded-full" onClick={saveNote} disabled={working}>
                Guardar nota
              </Button>
            </section>

            <section className="rounded-2xl border border-border bg-card p-4">
              <h3 className="flex items-center gap-2 text-sm font-semibold">
                <Link2 className="h-4 w-4 text-primary" /> Enlace de la clienta
              </h3>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                Con este enlace la clienta ve su apartado y tus datos para la transferencia. Le llegó por
                correo; si lo perdió o no le llegó, envíale uno nuevo y el anterior dejará de funcionar.
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
                  <Link2 className="mr-2 h-4 w-4" /> Enviar enlace nuevo a la clienta
                </Button>
                <Button
                  size="sm"
                  variant="outline"
                  disabled={working}
                  onClick={revokePrivateLink}
                  className="rounded-full !bg-transparent"
                >
                  <Unlink className="mr-2 h-4 w-4" /> Desactivar enlace
                </Button>
              </div>
              {privateLink ? (
                <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 p-3">
                  <Label htmlFor="crm-enlace-privado" className="text-xs font-semibold text-amber-950">
                    Si el correo no le llega, copia este enlace y mándaselo por WhatsApp. Sólo se muestra
                    ahora: cópialo antes de cerrar o cambiar de apartado.
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
                        {LINK_EMAIL_TEMPLATES.has(n.template) ? 'Enviar enlace nuevo' : 'Reenviar'}
                      </Button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-3 border-t border-border pt-3 text-xs font-semibold">Enviar un aviso por correo</p>
              <div className="mt-2 flex flex-wrap gap-2">
                {Object.keys(MANUAL_EMAIL_LABELS).map((template) => (
                  <Button
                    key={template}
                    size="sm"
                    variant="outline"
                    disabled={working}
                    onClick={() => resend(template)}
                    className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                  >
                    {MANUAL_EMAIL_LABELS[template]}
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
