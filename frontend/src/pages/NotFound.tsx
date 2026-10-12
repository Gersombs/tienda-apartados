import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { SHOP_NAME_FALLBACK, setSeo } from '@/lib/shop';

export default function NotFound() {
  useEffect(() => {
    setSeo({
      title: `Página no encontrada — ${SHOP_NAME_FALLBACK}`,
      description: 'La página que buscas no existe o cambió de dirección.',
      noindex: true,
    });
  }, []);

  return (
    <div className="mx-auto flex min-h-screen max-w-md flex-col justify-center px-4 py-10">
      <div className="rounded-2xl border border-border bg-card p-6">
        <p className="precio text-xs font-semibold uppercase tracking-[0.14em] text-primary">
          Error 404
        </p>
        <h1 className="mt-2 text-2xl">No encontramos esta página</h1>
        <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
          El enlace puede estar incompleto o el producto ya no está en el catálogo. Regresa al inicio o
          explora todo lo disponible.
        </p>
        <div className="mt-5 flex flex-wrap gap-2">
          <Button asChild className="tap rounded-full">
            <Link to="/">Ir al inicio</Link>
          </Button>
          <Button
            asChild
            variant="outline"
            className="tap rounded-full !bg-transparent hover:!bg-transparent"
          >
            <Link to="/catalogo">Ver catálogo</Link>
          </Button>
        </div>
      </div>
    </div>
  );
}