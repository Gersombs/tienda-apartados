import { useCallback, useEffect, useState } from 'react';
import { AlertTriangle, MapPin, Settings as SettingsIcon, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { confirmAction } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { WEEKDAY_NAMES, api, apiError } from '@/lib/shop';
import type { DeliveryConfig, SettingsResponse, ToastFn } from './types';
import { PhotoField } from './photos';

/* -------------------------- Configuración ------------------------ */
export type DeliverySlot = DeliveryConfig['slots'][number];
export type DeliveryPoint = DeliveryConfig['points'][number];

/** Horarios de un punto de entrega: alta, pausa y borrado. */
export function SlotsEditor({
  pointId,
  slots,
  toast,
  onChanged,
}: {
  pointId: number;
  slots: DeliverySlot[];
  toast: ToastFn;
  onChanged: () => void;
}) {
  const [draft, setDraft] = useState({ weekday: 0, start_time: '10:00', end_time: '12:00', capacity: '' });
  const [working, setWorking] = useState(false);

  const run = async (action: () => Promise<unknown>, message: string) => {
    setWorking(true);
    try {
      await action();
      toast({ title: message });
      onChanged();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const slotPayload = (slot: DeliverySlot, is_active: boolean) => ({
    delivery_point_id: slot.delivery_point_id,
    weekday: slot.weekday,
    start_time: slot.start_time,
    end_time: slot.end_time,
    capacity: slot.capacity,
    is_active,
  });

  return (
    <div className="mt-3">
      <p className="text-sm font-medium">Horarios</p>
      <p className="text-xs text-muted-foreground">Cada horario se guarda en cuanto lo agregas.</p>
      {slots.length === 0 ? (
        <p className="text-xs text-amber-800">Sin horarios: las clientas no podrán elegir este punto.</p>
      ) : (
        <ul className="mt-1 space-y-1">
          {slots.map((slot) => (
            <li key={slot.id} className="flex flex-wrap items-center gap-2 text-sm">
              <span className={`precio min-w-0 flex-1 ${slot.is_active ? '' : 'text-muted-foreground line-through'}`}>
                <span className="block font-medium">{WEEKDAY_NAMES[slot.weekday]}</span>
                <span className="block text-xs text-muted-foreground">
                  {slot.start_time}–{slot.end_time}
                  {slot.capacity > 0 ? ` · cupo ${slot.capacity}` : ' · sin límite'}
                </span>
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs"
                disabled={working}
                onClick={() =>
                  run(
                    () => api(`/api/v1/crm/delivery-slots/${slot.id}`, 'PUT', slotPayload(slot, !slot.is_active)),
                    slot.is_active ? 'Horario pausado' : 'Horario activado',
                  )
                }
              >
                {slot.is_active ? 'Pausar' : 'Activar'}
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-destructive"
                disabled={working}
                onClick={async () => {
                  const ok = await confirmAction({
                    title: '¿Eliminar este horario?',
                    description: `${WEEKDAY_NAMES[slot.weekday]} ${slot.start_time}–${slot.end_time}`,
                    confirmLabel: 'Eliminar',
                    destructive: true,
                  });
                  if (!ok) return;
                  void run(() => api(`/api/v1/crm/delivery-slots/${slot.id}`, 'DELETE'), 'Horario eliminado');
                }}
              >
                Eliminar
              </Button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-2 grid gap-2 sm:grid-cols-5">
        <div>
          <Label htmlFor={`slot-dia-${pointId}`}>Día</Label>
          <Select
            value={String(draft.weekday)}
            onValueChange={(value) => setDraft({ ...draft, weekday: Number(value) })}
          >
            <SelectTrigger id={`slot-dia-${pointId}`} className="tap mt-1">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {WEEKDAY_NAMES.map((day, index) => (
                <SelectItem key={day} value={String(index)}>
                  {day}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div>
          <Label htmlFor={`slot-inicio-${pointId}`}>Desde</Label>
          <Input
            id={`slot-inicio-${pointId}`}
            type="time"
            value={draft.start_time}
            onChange={(e) => setDraft({ ...draft, start_time: e.target.value })}
            className="precio tap mt-1"
          />
        </div>
        <div>
          <Label htmlFor={`slot-fin-${pointId}`}>Hasta</Label>
          <Input
            id={`slot-fin-${pointId}`}
            type="time"
            value={draft.end_time}
            onChange={(e) => setDraft({ ...draft, end_time: e.target.value })}
            className="precio tap mt-1"
          />
        </div>
        <div>
          <Label htmlFor={`slot-cupo-${pointId}`}>Cupo de apartados</Label>
          <Input
            id={`slot-cupo-${pointId}`}
            type="number"
            inputMode="numeric"
            min={0}
            value={draft.capacity}
            aria-describedby={`slot-cupo-ayuda-${pointId}`}
            onChange={(e) => setDraft({ ...draft, capacity: e.target.value })}
            className="precio tap mt-1"
          />
          <p id={`slot-cupo-ayuda-${pointId}`} className="mt-0.5 text-xs text-muted-foreground">
            Vacío = sin límite
          </p>
        </div>
        <div className="flex items-end">
          <Button
            size="sm"
            className="tap w-full rounded-full"
            disabled={working}
            onClick={() =>
              run(
                () =>
                  api('/api/v1/crm/delivery-slots', 'POST', {
                    ...draft,
                    capacity: Math.max(0, Number(draft.capacity) || 0),
                    delivery_point_id: pointId,
                    is_active: true,
                  }),
                'Horario agregado',
              )
            }
          >
            Agregar horario
          </Button>
        </div>
      </div>
    </div>
  );
}

export function SettingsTab({ toast }: { toast: ToastFn }) {
  const [data, setData] = useState<SettingsResponse | null>(null);
  const [delivery, setDelivery] = useState<DeliveryConfig | null>(null);
  const [store, setStore] = useState<Record<string, string | number>>({});
  const [priv, setPriv] = useState<Record<string, string>>({});
  // Cambios sin guardar por punto: recargar horarios o guardar otro punto no los borra.
  const [pointDrafts, setPointDrafts] = useState<Record<number, DeliveryPoint>>({});
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

  const refreshDelivery = useCallback(() => {
    api<DeliveryConfig>('/api/v1/crm/delivery')
      .then(setDelivery)
      .catch((e) => toast({ title: apiError(e), variant: 'destructive' }));
  }, [toast]);

  const editPoint = (saved: DeliveryPoint, patch: Partial<DeliveryPoint>) =>
    setPointDrafts((drafts) => ({ ...drafts, [saved.id]: { ...(drafts[saved.id] ?? saved), ...patch } }));

  const dropDraft = (id: number) =>
    setPointDrafts((drafts) => {
      const { [id]: _dropped, ...rest } = drafts;
      return rest;
    });

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

  const savePoint = async (point: DeliveryPoint) => {
    if (!point.name.trim()) {
      toast({ title: 'Escribe el nombre del punto de entrega.', variant: 'destructive' });
      return;
    }
    setWorking(true);
    try {
      // El backend rechaza campos extra: el id va en la URL, no en el cuerpo.
      const { id, ...fields } = point;
      await api(`/api/v1/crm/delivery-points/${id}`, 'PUT', fields);
      toast({ title: 'Punto de entrega guardado' });
      dropDraft(id);
      refreshDelivery();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const addPoint = async () => {
    setWorking(true);
    try {
      await api('/api/v1/crm/delivery-points', 'POST', {
        name: '',
        kind: 'metro',
        city: 'Ciudad de México',
        sort_order: delivery?.points.length ?? 0,
        is_active: false,
      });
      toast({ title: 'Punto agregado. Complétalo, actívalo y guárdalo.' });
      refreshDelivery();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const removePoint = async (point: DeliveryPoint) => {
    const ok = await confirmAction({
      title: `¿Eliminar «${point.name || 'este punto'}»?`,
      description: 'También se borrarán sus horarios.',
      confirmLabel: 'Eliminar',
      destructive: true,
    });
    if (!ok) return;
    setWorking(true);
    try {
      await api(`/api/v1/crm/delivery-points/${point.id}`, 'DELETE');
      toast({ title: 'Punto eliminado' });
      dropDraft(point.id);
      refreshDelivery();
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
          {textField('contact_email', 'Correo de contacto (aquí te responden las clientas)')}
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
              ['notification_from_name', 'Nombre que verán en los correos'],
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
          {delivery.points.map((saved) => {
            const point = pointDrafts[saved.id] ?? saved;
            const dirty = Boolean(pointDrafts[saved.id]);
            const slots = delivery.slots.filter((s) => s.delivery_point_id === point.id);
            return (
              <div key={point.id} className="rounded-xl border border-border p-3">
                <div className="grid gap-2 sm:grid-cols-2">
                  <div>
                    <Label htmlFor={`dp-name-${point.id}`}>Nombre (ej. Metro Insurgentes)</Label>
                    <Input
                      id={`dp-name-${point.id}`}
                      value={point.name}
                      onChange={(e) =>
                        editPoint(saved, { name: e.target.value })
                      }
                      className="tap mt-1"
                    />
                  </div>
                  <div>
                    <Label htmlFor={`dp-ref-${point.id}`}>Punto de encuentro (ej. salida a Génova)</Label>
                    <Input
                      id={`dp-ref-${point.id}`}
                      value={point.reference}
                      onChange={(e) =>
                        editPoint(saved, { reference: e.target.value })
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
                        editPoint(saved, { address: e.target.value })
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
                      editPoint(saved, { is_active: e.target.checked })
                    }
                    className="h-4 w-4 accent-primary"
                  />
                  Activo para nuevas reservaciones
                </label>
                <div className="mt-2 flex flex-wrap items-center gap-2">
                  <Button
                    size="sm"
                    className="tap rounded-full"
                    onClick={() => savePoint(point)}
                    disabled={working || !dirty}
                  >
                    Guardar datos del punto
                  </Button>
                  {dirty ? (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="text-xs"
                      onClick={() => dropDraft(point.id)}
                      disabled={working}
                    >
                      Descartar cambios
                    </Button>
                  ) : null}
                  <Button
                    size="sm"
                    variant="ghost"
                    className="text-xs text-destructive"
                    onClick={() => removePoint(point)}
                    disabled={working}
                  >
                    Eliminar punto
                  </Button>
                </div>
                {dirty ? (
                  <p className="mt-1 text-xs font-medium text-amber-800">
                    Tienes cambios sin guardar en este punto.
                  </p>
                ) : null}
                <SlotsEditor pointId={point.id} slots={slots} toast={toast} onChanged={refreshDelivery} />
              </div>
            );
          })}
        </div>
        <Button className="tap mt-4 rounded-full" onClick={addPoint} disabled={working}>
          Agregar punto de entrega
        </Button>
      </section>
    </div>
  );
}
