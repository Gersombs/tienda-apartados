import { ReactNode, useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { Home, Search, ShoppingBag, Instagram, MessageCircle, X } from 'lucide-react';
import {
  AVISO_SIN_PAGO,
  CartLine,
  StoreSettings,
  cart,
  cartTotals,
  pesos,
  whatsappLink,
  SHOP_NAME_FALLBACK,
} from '@/lib/shop';
import { Button } from '@/components/ui/button';

interface Props {
  children: ReactNode;
  settings: StoreSettings | null;
  /** Oculta la barra flotante del apartado (por ejemplo en la propia página del apartado). */
  hideCartBar?: boolean;
}

export function useCart() {
  const [lines, setLines] = useState<CartLine[]>(() => cart.read());
  useEffect(() => {
    const unsubscribe = cart.subscribe(setLines);
    const onStorage = () => setLines(cart.read());
    window.addEventListener('storage', onStorage);
    return () => {
      unsubscribe();
      window.removeEventListener('storage', onStorage);
    };
  }, []);
  return lines;
}

function CartPanel({
  lines,
  onClose,
}: {
  lines: CartLine[];
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const { count, total } = cartTotals(lines);

  return (
    <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-label="Mi apartado">
      <button
        type="button"
        aria-label="Cerrar panel"
        className="absolute inset-0 bg-foreground/40"
        onClick={onClose}
      />
      <div className="relative z-10 max-h-[82vh] w-full overflow-y-auto rounded-t-3xl border-t border-border bg-card p-5 pb-8 animate-in slide-in-from-bottom-8 duration-300 sm:mx-auto sm:max-w-lg sm:rounded-3xl sm:mb-6">
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-xl">Mi apartado</h2>
            <p className="text-sm text-muted-foreground">
              {count === 1 ? '1 artículo' : `${count} artículos`}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Cerrar"
            className="tap flex items-center justify-center rounded-full border border-border text-foreground hover:bg-secondary"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <ul className="space-y-3">
          {lines.map((line) => (
            <li key={line.variantId} className="flex gap-3 rounded-xl border border-border bg-background p-3">
              <img
                src={line.imageUrl}
                alt={line.name}
                loading="lazy"
                className="h-16 w-16 flex-shrink-0 rounded-lg object-cover"
              />
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-semibold">{line.name}</p>
                <p className="truncate text-xs text-muted-foreground">{line.variantLabel}</p>
                <div className="mt-2 flex items-center gap-2">
                  <div className="flex items-center gap-1 rounded-full border border-border">
                    <button
                      type="button"
                      aria-label={`Quitar una pieza de ${line.name}`}
                      onClick={() => cart.setQuantity(line.variantId, line.quantity - 1)}
                      className="h-9 w-9 rounded-full text-lg leading-none hover:bg-secondary"
                    >
                      −
                    </button>
                    <span className="precio w-6 text-center text-sm">{line.quantity}</span>
                    <button
                      type="button"
                      aria-label={`Agregar una pieza de ${line.name}`}
                      disabled={line.quantity >= line.maxUnits}
                      onClick={() => cart.setQuantity(line.variantId, line.quantity + 1)}
                      className="h-9 w-9 rounded-full text-lg leading-none hover:bg-secondary disabled:opacity-40"
                    >
                      +
                    </button>
                  </div>
                  <span className="precio ml-auto text-sm font-semibold">
                    {pesos(line.unitPrice * line.quantity)}
                  </span>
                </div>
              </div>
            </li>
          ))}
        </ul>

        <div className="mt-5 flex items-center justify-between border-t border-border pt-4">
          <span className="text-sm font-medium">Total a pagar al entregar</span>
          <span className="precio text-2xl font-bold text-primary">{pesos(total)}</span>
        </div>
        <p className="mt-2 text-xs leading-relaxed text-muted-foreground">{AVISO_SIN_PAGO}</p>

        <Button
          className="tap mt-4 w-full rounded-full text-base"
          onClick={() => {
            onClose();
            navigate('/apartado');
          }}
        >
          Continuar con mi apartado
        </Button>
      </div>
    </div>
  );
}

export default function ShopLayout({ children, settings, hideCartBar = false }: Props) {
  const lines = useCart();
  const { count, total } = cartTotals(lines);
  const [panelOpen, setPanelOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setPanelOpen(false);
  }, [location.pathname]);

  const nav = [
    { to: '/', label: 'Inicio', icon: Home },
    { to: '/catalogo', label: 'Catálogo', icon: Search },
    { to: '/apartado', label: 'Mi apartado', icon: ShoppingBag },
  ];

  const shopName = settings?.shop_name || SHOP_NAME_FALLBACK;
  const showBar = !hideCartBar && count > 0;

  return (
    <div className="flex min-h-screen flex-col bg-background">
      <header className="sticky top-0 z-30 border-b border-border bg-background/95 backdrop-blur-sm">
        <div className="mx-auto flex w-full max-w-screen-xl items-center gap-3 px-4 py-3">
          <Link to="/" className="flex min-w-0 items-center gap-2">
            {settings?.logo_url ? (
              <img
                src={settings.logo_url}
                alt={shopName}
                className="h-9 w-9 flex-shrink-0 rounded-full object-contain"
              />
            ) : null}
            <span className="display truncate text-base font-bold tracking-tight">{shopName}</span>
          </Link>

          <nav className="ml-auto hidden items-center gap-1 md:flex">
            {nav.map((item) => (
              <Link
                key={item.to}
                to={item.to}
                className={`tap flex items-center rounded-full px-4 text-sm font-medium transition-colors ${
                  location.pathname === item.to
                    ? 'bg-secondary text-foreground'
                    : 'text-muted-foreground hover:md:bg-secondary hover:md:text-foreground'
                }`}
              >
                {item.label}
              </Link>
            ))}
            <Link
              to="/como-funciona"
              className="tap flex items-center rounded-full px-4 text-sm font-medium text-muted-foreground hover:md:bg-secondary hover:md:text-foreground"
            >
              Cómo funciona
            </Link>
          </nav>

          <button
            type="button"
            onClick={() => setPanelOpen(true)}
            aria-label={`Abrir mi apartado, ${count} artículos`}
            className="tap relative ml-auto flex items-center justify-center rounded-full border border-border text-foreground hover:bg-secondary md:ml-0"
          >
            <ShoppingBag className="h-5 w-5" />
            {count > 0 && (
              <span className="precio absolute -right-1 -top-1 flex h-5 min-w-5 items-center justify-center rounded-full bg-primary px-1 text-[11px] font-bold text-primary-foreground">
                {count}
              </span>
            )}
          </button>
        </div>
      </header>

      <main className="mx-auto w-full max-w-screen-xl flex-1 px-4 pb-32 pt-4 md:pb-16">{children}</main>

      <footer className="border-t border-border bg-secondary/60 px-4 pb-24 pt-8 md:pb-8">
        <div className="mx-auto w-full max-w-screen-xl">
          <p className="display text-lg font-semibold">{shopName}</p>
          {settings?.tagline ? (
            <p className="mt-1 text-sm text-muted-foreground">{settings.tagline}</p>
          ) : null}
          <p className="mt-3 max-w-prose text-sm leading-relaxed text-muted-foreground">
            {AVISO_SIN_PAGO}
          </p>

          <div className="mt-5 grid gap-2 text-sm sm:grid-cols-2">
            <Link className="w-fit text-foreground underline-offset-4 hover:underline" to="/como-funciona">
              Cómo funciona
            </Link>
            <Link className="w-fit text-foreground underline-offset-4 hover:underline" to="/preguntas-frecuentes">
              Preguntas frecuentes
            </Link>
            <Link className="w-fit text-foreground underline-offset-4 hover:underline" to="/politicas-de-apartado">
              Políticas de apartado
            </Link>
            <Link className="w-fit text-foreground underline-offset-4 hover:underline" to="/aviso-de-privacidad">
              Aviso de privacidad
            </Link>
          </div>

          <div className="mt-5 flex flex-wrap items-center gap-3">
            {settings?.contact_whatsapp ? (
              <a
                href={whatsappLink(settings.contact_whatsapp, 'Hola, tengo una duda sobre mi apartado.')}
                target="_blank"
                rel="noreferrer"
                className="tap inline-flex items-center gap-2 rounded-full border border-border bg-background px-4 text-sm font-medium"
              >
                <MessageCircle className="h-4 w-4" /> WhatsApp
              </a>
            ) : null}
            {settings?.instagram_url ? (
              <a
                href={settings.instagram_url}
                target="_blank"
                rel="noreferrer"
                className="tap inline-flex items-center gap-2 rounded-full border border-border bg-background px-4 text-sm font-medium"
              >
                <Instagram className="h-4 w-4" /> Instagram
              </a>
            ) : null}
            {settings?.tiktok_url ? (
              <a
                href={settings.tiktok_url}
                target="_blank"
                rel="noreferrer"
                className="tap inline-flex items-center rounded-full border border-border bg-background px-4 text-sm font-medium"
              >
                TikTok
              </a>
            ) : null}
          </div>

          {settings?.contact_email ? (
            <p className="mt-5 text-xs text-muted-foreground">Contacto: {settings.contact_email}</p>
          ) : null}
          <p className="mt-1 text-xs text-muted-foreground">
            Entregas personales en estaciones del Metro y plazas de la Ciudad de México.
          </p>
        </div>
      </footer>

      {showBar && (
        <button
          type="button"
          onClick={() => setPanelOpen(true)}
          className="fixed bottom-[76px] left-1/2 z-30 flex w-[calc(100%-2rem)] max-w-md -translate-x-1/2 items-center gap-3 rounded-full bg-foreground px-5 py-3 text-background shadow-lg md:bottom-6"
        >
          <ShoppingBag className="h-5 w-5 flex-shrink-0" />
          <span className="precio text-sm font-semibold">
            {count === 1 ? '1 artículo' : `${count} artículos`}
          </span>
          <span className="precio ml-auto text-base font-bold">{pesos(total)}</span>
        </button>
      )}

      <nav
        aria-label="Navegación principal"
        className="fixed bottom-0 left-0 right-0 z-30 border-t border-border bg-background md:hidden"
      >
        <div className="grid grid-cols-3">
          {nav.map((item) => {
            const Icon = item.icon;
            const active = location.pathname === item.to;
            return (
              <Link
                key={item.to}
                to={item.to}
                className={`tap flex flex-col items-center justify-center gap-1 py-2 text-[11px] font-medium ${
                  active ? 'text-primary' : 'text-muted-foreground'
                }`}
              >
                <span className="relative">
                  <Icon className="h-5 w-5" />
                  {item.to === '/apartado' && count > 0 && (
                    <span className="precio absolute -right-2 -top-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-primary px-1 text-[10px] font-bold text-primary-foreground">
                      {count}
                    </span>
                  )}
                </span>
                {item.label}
              </Link>
            );
          })}
        </div>
      </nav>

      {panelOpen && lines.length > 0 && <CartPanel lines={lines} onClose={() => setPanelOpen(false)} />}
      {panelOpen && lines.length === 0 && (
        <div className="fixed inset-0 z-50 flex items-end" role="dialog" aria-label="Mi apartado vacío">
          <button
            type="button"
            aria-label="Cerrar panel"
            className="absolute inset-0 bg-foreground/40"
            onClick={() => setPanelOpen(false)}
          />
          <div className="relative z-10 w-full rounded-t-3xl border-t border-border bg-card p-6 pb-10 sm:mx-auto sm:max-w-lg sm:mb-6 sm:rounded-3xl">
            <h2 className="text-xl">Tu apartado está vacío</h2>
            <p className="mt-2 text-sm text-muted-foreground">
              Explora el catálogo y agrega tus productos favoritos para reservarlos sin anticipo.
            </p>
            <Button
              className="tap mt-4 w-full rounded-full"
              onClick={() => setPanelOpen(false)}
              asChild
            >
              <Link to="/catalogo">Ver catálogo</Link>
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}