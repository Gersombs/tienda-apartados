import { useCallback, useEffect, useState } from 'react';
import { BadgeCheck, Boxes, CalendarDays } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { api, apiError, fechaCorta, fechaHora, pesos } from '@/lib/shop';
import type { Dashboard } from './types';

/* --------------------------- Dashboard --------------------------- */
export function StatCard({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-2xl border border-border bg-card p-4">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className="precio mt-1 text-2xl font-bold">{value}</p>
      {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  );
}

export function DashboardTab({ onOpenReservations }: { onOpenReservations: () => void }) {
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
