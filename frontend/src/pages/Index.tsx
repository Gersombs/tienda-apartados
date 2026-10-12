import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, CalendarCheck, MapPin, Sparkles } from 'lucide-react';
import ShopLayout from '@/components/ShopLayout';
import ProductCardItem from '@/components/ProductCardItem';
import TrustPoints from '@/components/TrustPoints';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Category,
  DeliveryPoint,
  ProductCard,
  StoreSettings,
  api,
  apiError,
  setSeo,
  SHOP_NAME_FALLBACK,
} from '@/lib/shop';

interface Bootstrap {
  settings: StoreSettings;
  categories: Category[];
  featured: ProductCard[];
  delivery_points: DeliveryPoint[];
}

const PASOS = [
  {
    icon: Sparkles,
    titulo: 'Elige tus productos',
    texto: 'Explora el catálogo, selecciona tono o presentación y agrégalos a Mi apartado.',
  },
  {
    icon: CalendarCheck,
    titulo: 'Agenda tu entrega',
    texto: 'Selecciona punto, fecha y horario disponible dentro de los próximos días.',
  },
  {
    icon: MapPin,
    titulo: 'Recibe y transfiere',
    texto: 'Nos vemos en el punto acordado y ahí realizas la transferencia del total.',
  },
];

// Clases fijas para que Tailwind las incluya; con pocas categorías la rejilla no queda medio vacía.
const COLUMNAS_CATEGORIAS = ['sm:grid-cols-1', 'sm:grid-cols-1', 'sm:grid-cols-2', 'sm:grid-cols-3', 'sm:grid-cols-4'];

export default function Index() {
  const [data, setData] = useState<Bootstrap | null>(null);
  const [error, setError] = useState('');

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const result = await api<Bootstrap>('/api/v1/shop/bootstrap');
        if (!cancelled) setData(result);
      } catch (e) {
        if (!cancelled) setError(apiError(e, 'No pudimos cargar la tienda.'));
      }
    };
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    const name = data?.settings.shop_name || SHOP_NAME_FALLBACK;
    setSeo({
      title: `${name} — Aparta cosméticos y recíbelos en el Metro o plazas de CDMX`,
      description:
        'Aparta labiales, bases, sombras y cuidado de la piel sin anticipo. Entrega personal en estaciones del Metro y plazas comerciales de la Ciudad de México.',
      image: data?.settings.hero_image_url,
    });
  }, [data]);

  const puntos = data?.delivery_points || [];

  return (
    <ShopLayout settings={data?.settings || null}>
      {error ? (
        <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-5">
          <h2 className="text-lg">No pudimos cargar la tienda</h2>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <Button className="tap mt-4 rounded-full" onClick={() => window.location.reload()}>
            Volver a intentar
          </Button>
        </div>
      ) : null}

      {/* Hero asimétrico */}
      <section className="grid gap-5 lg:grid-cols-5 lg:items-center lg:gap-8">
        <div className="lg:col-span-3">
          <p className="text-xs font-semibold uppercase tracking-[0.14em] text-primary">
            Apartado sin anticipo
          </p>
          <h1 className="mt-2 text-[2rem] leading-[1.1] sm:text-4xl lg:text-5xl">
            Aparta tus cosméticos hoy y págalos cuando te los entregamos
          </h1>
          <p className="mt-4 max-w-prose text-base leading-relaxed text-muted-foreground">
            {data?.settings.tagline ||
              'Cosmética contemporánea con entrega personal en estaciones del Metro y plazas comerciales de la Ciudad de México.'}
          </p>
          <div className="mt-6 flex flex-wrap gap-3">
            <Button asChild className="tap rounded-full px-6 text-base">
              <Link to="/catalogo">
                Ver catálogo <ArrowRight className="ml-1 h-4 w-4" />
              </Link>
            </Button>
            <Button
              asChild
              variant="outline"
              className="tap rounded-full !bg-transparent px-6 text-base hover:!bg-transparent"
            >
              <Link to="/como-funciona">Cómo funciona</Link>
            </Button>
          </div>
          <TrustPoints className="mt-6" />
        </div>

        <div className="overflow-hidden rounded-3xl bg-muted shadow-xl shadow-foreground/10 lg:col-span-2">
          {data?.settings.hero_image_url ? (
            <img
              src={data.settings.hero_image_url}
              alt="Labiales, polvo compacto y sérum sobre lino marfil con luz suave"
              width={1024}
              height={576}
              className="aspect-[4/3] w-full object-cover lg:aspect-[3/4]"
            />
          ) : (
            <Skeleton className="aspect-[4/3] w-full lg:aspect-[3/4]" />
          )}
        </div>
      </section>

      {/* Categorías */}
      <section className="mt-12">
        <h2>Explora por categoría</h2>
        {!data ? (
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="aspect-[4/3] rounded-2xl" />
            ))}
          </div>
        ) : (
          <div
            className={`mt-4 grid grid-cols-2 gap-3 ${COLUMNAS_CATEGORIAS[Math.min(data.categories.length, 4)]}`}
          >
            {data.categories.map((category) => (
              <Link
                key={category.slug}
                to={`/categoria/${category.slug}`}
                className="group relative overflow-hidden rounded-2xl"
              >
                <img
                  src={category.image_url}
                  alt=""
                  loading="lazy"
                  className={`w-full object-cover transition-transform duration-500 group-hover:md:scale-105 ${
                    data.categories.length < 3 ? 'aspect-[4/3] sm:aspect-[2/1]' : 'aspect-[4/3]'
                  }`}
                />
                <span className="absolute inset-0 bg-gradient-to-t from-black/65 via-black/10 to-transparent" />
                <span className="display absolute inset-x-0 bottom-0 flex items-center justify-between p-3 text-base font-semibold text-white sm:p-4 sm:text-lg">
                  {category.name}
                  <ArrowRight className="h-4 w-4 transition-transform group-hover:md:translate-x-1" />
                </span>
              </Link>
            ))}
          </div>
        )}
      </section>

      {/* Destacados */}
      <section className="mt-12">
        <div className="flex items-end justify-between gap-3">
          <h2>Favoritos de la temporada</h2>
          <Link
            to="/catalogo"
            className="flex-shrink-0 text-sm font-semibold text-primary underline-offset-4 hover:underline"
          >
            Ver todo
          </Link>
        </div>
        {!data ? (
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="aspect-[3/4] rounded-2xl" />
            ))}
          </div>
        ) : data.featured.length === 0 ? (
          <p className="mt-4 rounded-2xl border border-border bg-card p-5 text-sm text-muted-foreground">
            Aún no hay productos destacados. Revisa el catálogo completo para ver todo lo disponible.
          </p>
        ) : (
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {data.featured.map((product) => (
              <ProductCardItem key={product.slug} product={product} />
            ))}
          </div>
        )}
      </section>

      {/* Cómo funciona */}
      <section className="mt-12 rounded-3xl bg-accent/60 p-5 sm:p-8">
        <h2>Así funciona tu apartado</h2>
        <div className="mt-6 grid gap-6 sm:grid-cols-3">
          {PASOS.map((paso, index) => {
            const Icon = paso.icon;
            return (
              <div key={paso.titulo}>
                <div className="flex items-center gap-3">
                  <span className="flex h-10 w-10 items-center justify-center rounded-full bg-primary text-primary-foreground">
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="precio text-xs font-bold tracking-wider text-accent-foreground">
                    PASO {index + 1}
                  </span>
                </div>
                <h3 className="mt-3 text-base">{paso.titulo}</h3>
                <p className="mt-1 text-sm leading-relaxed text-muted-foreground">{paso.texto}</p>
              </div>
            );
          })}
        </div>
      </section>

      {/* Puntos de entrega */}
      <section className="mt-12">
        <h2>Dónde te entregamos</h2>
        <p className="mt-1 max-w-prose text-sm text-muted-foreground">
          Elige el punto que te quede más cerca al momento de enviar tu solicitud de apartado.
        </p>
        {!data ? (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-28 rounded-2xl" />
            ))}
          </div>
        ) : puntos.length === 0 ? (
          <p className="mt-4 rounded-2xl border border-border bg-card p-5 text-sm text-muted-foreground">
            Estamos actualizando nuestros puntos de entrega. Escríbenos por WhatsApp para coordinar.
          </p>
        ) : (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {puntos.map((point) => (
              <div key={point.id} className="rounded-2xl border border-border bg-card p-4">
                <div className="flex items-start gap-2">
                  <MapPin className="mt-0.5 h-4 w-4 flex-shrink-0 text-primary" />
                  <div className="min-w-0">
                    <h3 className="text-sm">{point.name}</h3>
                    <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                      {point.reference || point.address}
                    </p>
                    <p className="mt-2 text-xs text-muted-foreground">
                      {point.days.length > 0
                        ? `${point.days.length} ${point.days.length === 1 ? 'día' : 'días'} con horarios disponibles`
                        : 'Sin horarios disponibles por ahora'}
                    </p>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </section>
    </ShopLayout>
  );
}
