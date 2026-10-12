import { type FormEvent, useEffect, useState } from 'react';
import { AlertTriangle, Loader2, LogOut, ShieldCheck } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { ConfirmDialogHost } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { useToast } from '@/hooks/use-toast';
import { api, apiError, setSeo } from '@/lib/shop';
import { CatalogTab } from './admin/CatalogTab';
import { DashboardTab } from './admin/DashboardTab';
import { ReservationsTab } from './admin/ReservationsTab';
import type { SessionState, SettingsResponse } from './admin/types';
import { SettingsTab } from './admin/SettingsTab';

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
  const [shopName, setShopName] = useState('');
  useEffect(() => {
    api<SettingsResponse>('/api/v1/crm/settings')
      .then((s) => setShopName(String(s.store.shop_name || '')))
      .catch(() => undefined);
  }, []);
  const logout = async () => {
    try {
      await api('/api/v1/auth/logout', 'POST');
    } finally {
      window.location.assign('/admin');
    }
  };

  return (
    <div className="min-h-screen bg-background">
      <ConfirmDialogHost />
      <header className="sticky top-0 z-20 border-b border-border bg-background/95 px-4 py-3 backdrop-blur">
        <div className="mx-auto flex w-full max-w-screen-xl items-center gap-3">
          <div className="min-w-0">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">CRM</p>
            <h1 className="truncate text-lg">{shopName}</h1>
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
          <TabsList className="grid h-auto w-full grid-cols-4">
            <TabsTrigger value="dashboard" className="min-h-11 px-1 text-xs sm:text-sm">
              Panel
            </TabsTrigger>
            <TabsTrigger value="reservaciones" className="min-h-11 px-1 text-xs sm:text-sm">
              Reservaciones
            </TabsTrigger>
            <TabsTrigger value="catalogo" className="min-h-11 px-1 text-xs sm:text-sm">
              Catálogo
            </TabsTrigger>
            <TabsTrigger value="config" className="min-h-11 px-1 text-xs sm:text-sm">
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
