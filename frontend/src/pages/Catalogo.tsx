import { useCallback, useEffect, useMemo, useState } from 'react';
import { useParams, useSearchParams } from 'react-router-dom';
import { Search, SlidersHorizontal, X } from 'lucide-react';
import ShopLayout from '@/components/ShopLayout';
import ProductCardItem from '@/components/ProductCardItem';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Category,
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
}

interface ProductsResponse {
  items: ProductCard[];
  total: number;
  category: Category | null;
}

const ORDENES = [
  { value: 'destacados', label: 'Destacados' },
  { value: 'precio_asc', label: 'Menor precio' },
  { value: 'precio_desc', label: 'Mayor precio' },
  { value: 'novedades', label: 'Novedades' },
];

const DISPONIBILIDAD = [
  { value: 'todos', label: 'Todo' },
  { value: 'disponibles', label: 'Disponibles' },
  { value: 'ultimas', label: 'Últimas piezas' },
];

const RANGOS = [
  { value: '0-0', label: 'Cualquier precio' },
  { value: '0-199', label: 'Hasta $199' },
  { value: '200-349', label: '$200 a $349' },
  { value: '350-499', label: '$350 a $499' },
  { value: '500-0', label: 'Más de $500' },
];

export default function Catalogo() {
  const { slug } = useParams<{ slug?: string }>();
  const [searchParams, setSearchParams] = useSearchParams();

  const [settings, setSettings] = useState<StoreSettings | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [items, setItems] = useState<ProductCard[]>([]);
  const [categoryInfo, setCategoryInfo] = useState<Category | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [filtersOpen, setFiltersOpen] = useState(false);

  const search = searchParams.get('q') || '';
  const sort = searchParams.get('orden') || 'destacados';
  const availability = searchParams.get('disp') || 'todos';
  const range = searchParams.get('precio') || '0-0';
  const activeCategory = slug || searchParams.get('categoria') || '';
  const filtered = Boolean(search || activeCategory || availability !== 'todos' || range !== '0-0');

  const [searchDraft, setSearchDraft] = useState(search);

  useEffect(() => {
    setSearchDraft(search);
  }, [search]);

  useEffect(() => {
    let cancelled = false;
    api<Bootstrap>('/api/v1/shop/bootstrap')
      .then((result) => {
        if (cancelled) return;
        setSettings(result.settings);
        setCategories(result.categories);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, []);

  const updateParam = useCallback(
    (key: string, value: string) => {
      const next = new URLSearchParams(searchParams);
      if (!value || value === 'todos' || value === 'destacados' || value === '0-0') {
        next.delete(key);
      } else {
        next.set(key, value);
      }
      setSearchParams(next, { replace: true });
    },
    [searchParams, setSearchParams],
  );

  useEffect(() => {
    let cancelled = false;
    const [minPrice, maxPrice] = range.split('-').map((v) => Number(v) || 0);
    setLoading(true);
    setError('');
    const timer = window.setTimeout(() => {
      api<ProductsResponse>('/api/v1/shop/products', 'GET', {
        search,
        category: activeCategory,
        sort,
        availability,
        min_price: minPrice,
        max_price: maxPrice,
      })
        .then((result) => {
          if (cancelled) return;
          setItems(result.items);
          setCategoryInfo(result.category);
        })
        .catch((e) => {
          if (!cancelled) setError(apiError(e, 'No pudimos cargar el catálogo.'));
        })
        .finally(() => {
          if (!cancelled) setLoading(false);
        });
    }, 180);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [search, activeCategory, sort, availability, range]);

  useEffect(() => {
    const shopName = settings?.shop_name || SHOP_NAME_FALLBACK;
    if (categoryInfo) {
      setSeo({
        title: `${categoryInfo.name} — ${shopName}`,
        description:
          categoryInfo.description ||
          `Aparta productos de ${categoryInfo.name} y recíbelos en el Metro o plazas de la Ciudad de México.`,
        image: categoryInfo.image_url,
      });
    } else {
      setSeo({
        title: `Catálogo completo — ${shopName}`,
        description:
          'Explora labiales, rostro, ojos y cuidado de la piel. Aparta sin anticipo y paga por transferencia al recibir.',
      });
    }
  }, [categoryInfo, settings]);

  const hasFilters = useMemo(
    () => Boolean(search || availability !== 'todos' || range !== '0-0' || sort !== 'destacados'),
    [search, availability, range, sort],
  );

  const titulo = categoryInfo ? categoryInfo.name : 'Catálogo';

  return (
    <ShopLayout settings={settings}>
      <header>
        <h1 className="text-[1.75rem] sm:text-3xl">{titulo}</h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">
          {categoryInfo?.description ||
            'Apartas hoy, pagas por transferencia cuando te entregamos en persona.'}
        </p>
      </header>

      {/* Buscador */}
      <form
        className="mt-4 flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          updateParam('q', searchDraft.trim());
        }}
      >
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
          <Label htmlFor="buscador" className="sr-only">
            Buscar productos
          </Label>
          <Input
            id="buscador"
            value={searchDraft}
            onChange={(event) => setSearchDraft(event.target.value)}
            placeholder="Buscar labial, base, sérum…"
            className="tap rounded-full pl-9"
            autoComplete="off"
          />
          {searchDraft ? (
            <button
              type="button"
              aria-label="Limpiar búsqueda"
              onClick={() => {
                setSearchDraft('');
                updateParam('q', '');
              }}
              className="absolute right-2 top-1/2 flex h-8 w-8 -translate-y-1/2 items-center justify-center rounded-full hover:bg-secondary"
            >
              <X className="h-4 w-4" />
            </button>
          ) : null}
        </div>
        <Button type="submit" className="tap rounded-full px-5">
          Buscar
        </Button>
      </form>

      {/* Chips de categoría */}
      <div className="chips mt-3 flex gap-2 overflow-x-auto pb-1">
        <button
          type="button"
          onClick={() => {
            const next = new URLSearchParams(searchParams);
            next.delete('categoria');
            if (slug) {
              window.location.href = `/catalogo?${next.toString()}`;
              return;
            }
            setSearchParams(next, { replace: true });
          }}
          className={`tap flex flex-shrink-0 items-center rounded-full border px-4 text-sm font-medium ${
            !activeCategory
              ? 'border-primary bg-primary text-primary-foreground'
              : 'border-border bg-card text-foreground'
          }`}
        >
          Todo
        </button>
        {categories.map((category) => {
          const active = activeCategory === category.slug;
          return (
            <a
              key={category.slug}
              href={`/categoria/${category.slug}`}
              className={`tap flex flex-shrink-0 items-center rounded-full border px-4 text-sm font-medium ${
                active
                  ? 'border-primary bg-primary text-primary-foreground'
                  : 'border-border bg-card text-foreground'
              }`}
            >
              {category.name}
            </a>
          );
        })}
      </div>

      {/* Filtros y orden */}
      <div className="mt-3 flex items-center gap-2">
        <Button
          type="button"
          variant="outline"
          onClick={() => setFiltersOpen((open) => !open)}
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
          aria-expanded={filtersOpen}
        >
          <SlidersHorizontal className="mr-2 h-4 w-4" />
          Filtros
        </Button>
        <Select value={sort} onValueChange={(value) => updateParam('orden', value)}>
          <SelectTrigger aria-label="Ordenar productos" className="tap ml-auto w-auto gap-1.5 rounded-full px-4">
            <span className="text-muted-foreground">Ordenar:</span>
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            {ORDENES.map((option) => (
              <SelectItem key={option.value} value={option.value}>
                {option.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {filtersOpen ? (
        <div className="mt-3 space-y-4 rounded-2xl border border-border bg-card p-4 animate-in fade-in duration-200">
          <fieldset>
            <legend className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Disponibilidad
            </legend>
            <div className="chips mt-2 flex gap-2 overflow-x-auto">
              {DISPONIBILIDAD.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => updateParam('disp', option.value)}
                  className={`tap flex flex-shrink-0 items-center rounded-full border px-4 text-sm ${
                    availability === option.value
                      ? 'border-primary bg-accent text-accent-foreground'
                      : 'border-border bg-background'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>

          <fieldset>
            <legend className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Precio
            </legend>
            <div className="chips mt-2 flex gap-2 overflow-x-auto">
              {RANGOS.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  onClick={() => updateParam('precio', option.value)}
                  className={`precio tap flex flex-shrink-0 items-center rounded-full border px-4 text-sm ${
                    range === option.value
                      ? 'border-primary bg-accent text-accent-foreground'
                      : 'border-border bg-background'
                  }`}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </fieldset>

          {hasFilters ? (
            <Button
              type="button"
              variant="ghost"
              className="tap px-0 text-primary"
              onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
            >
              Limpiar filtros
            </Button>
          ) : null}
        </div>
      ) : null}

      {/* Resultados */}
      <section className="mt-5">
        {loading ? (
          <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
            {[0, 1, 2, 3, 4, 5].map((i) => (
              <Skeleton key={i} className="aspect-[3/4] rounded-2xl" />
            ))}
          </div>
        ) : error ? (
          <div className="rounded-2xl border border-destructive/40 bg-destructive/10 p-5">
            <h2 className="text-lg">No pudimos cargar el catálogo</h2>
            <p className="mt-1 text-sm text-muted-foreground">{error}</p>
            <Button className="tap mt-4 rounded-full" onClick={() => window.location.reload()}>
              Volver a intentar
            </Button>
          </div>
        ) : items.length === 0 && !filtered ? (
          <div className="rounded-2xl border border-border bg-card p-6 text-center">
            <h2 className="text-lg">Muy pronto habrá productos</h2>
            <p className="mx-auto mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
              Estamos preparando el catálogo. Vuelve en unos días para apartar tus favoritos.
            </p>
          </div>
        ) : items.length === 0 ? (
          <div className="rounded-2xl border border-border bg-card p-6 text-center">
            <h2 className="text-lg">Sin resultados por ahora</h2>
            <p className="mx-auto mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
              No encontramos productos con esa combinación. Prueba con otra palabra o quita algún filtro
              para ver más opciones.
            </p>
            <Button
              className="tap mt-4 rounded-full"
              onClick={() => setSearchParams(new URLSearchParams(), { replace: true })}
            >
              Ver todo el catálogo
            </Button>
          </div>
        ) : (
          <>
            <p className="precio mb-3 text-sm text-muted-foreground">
              {items.length === 1 ? '1 producto' : `${items.length} productos`}
            </p>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              {items.map((product) => (
                <ProductCardItem key={product.slug} product={product} />
              ))}
            </div>
          </>
        )}
      </section>
    </ShopLayout>
  );
}
