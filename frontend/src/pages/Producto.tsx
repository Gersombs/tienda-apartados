import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ChevronLeft, Link2, MessageCircle, Check } from 'lucide-react';
import ShopLayout from '@/components/ShopLayout';
import ProductCardItem from '@/components/ProductCardItem';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { useToast } from '@/hooks/use-toast';
import {
  AVISO_SIN_PAGO,
  ProductCard,
  ProductDetail,
  ProductVariant,
  StoreSettings,
  api,
  apiError,
  cart,
  pesos,
  setProductJsonLd,
  setSeo,
  whatsappLink,
  SHOP_NAME_FALLBACK,
} from '@/lib/shop';

interface DetailResponse {
  product: ProductDetail;
  related: ProductCard[];
}

interface Bootstrap {
  settings: StoreSettings;
}

export default function Producto() {
  const { slug = '' } = useParams<{ slug: string }>();
  const { toast } = useToast();

  const [settings, setSettings] = useState<StoreSettings | null>(null);
  const [data, setData] = useState<DetailResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [variantId, setVariantId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState(1);
  const [imageIndex, setImageIndex] = useState(0);
  const [added, setAdded] = useState(false);

  useEffect(() => {
    api<Bootstrap>('/api/v1/shop/bootstrap')
      .then((result) => setSettings(result.settings))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError('');
    setImageIndex(0);
    setQuantity(1);
    setAdded(false);
    api<DetailResponse>(`/api/v1/shop/products/${slug}`)
      .then((result) => {
        if (cancelled) return;
        setData(result);
        const firstAvailable =
          result.product.variants.find((v) => v.available_units > 0) || result.product.variants[0];
        setVariantId(firstAvailable ? firstAvailable.id : null);
      })
      .catch((e) => {
        if (!cancelled) setError(apiError(e, 'No encontramos este producto.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [slug]);

  const product = data?.product || null;

  useEffect(() => {
    if (!product) return;
    setSeo({
      title: `${product.name} — ${settings?.shop_name || SHOP_NAME_FALLBACK}`,
      description: product.short_description,
      image: product.image_url,
    });
    setProductJsonLd(product);
    return () => setProductJsonLd(null);
  }, [product, settings]);

  const variant: ProductVariant | null = useMemo(() => {
    if (!product) return null;
    return product.variants.find((v) => v.id === variantId) || null;
  }, [product, variantId]);

  const maxUnits = variant?.available_units ?? 0;
  const unitPrice = variant?.price ?? product?.price ?? 0;

  const handleAdd = () => {
    if (!product || !variant) return;
    const result = cart.add(
      {
        variantId: variant.id,
        slug: product.slug,
        name: product.name,
        variantLabel: variant.label,
        unitPrice: variant.price,
        imageUrl: product.images[0]?.url || product.image_url,
        maxUnits: variant.available_units,
      },
      quantity,
    );
    if (!result.ok) {
      toast({ title: result.message || 'No pudimos agregarlo', variant: 'destructive' });
      return;
    }
    setAdded(true);
    toast({ title: `${product.name} se agregó a Mi apartado` });
    window.setTimeout(() => setAdded(false), 2200);
  };

  const shareUrl = typeof window !== 'undefined' ? window.location.href : '';

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(shareUrl);
      toast({ title: 'Enlace copiado' });
    } catch {
      toast({ title: 'No pudimos copiar el enlace', variant: 'destructive' });
    }
  };

  if (loading) {
    return (
      <ShopLayout settings={settings}>
        <Skeleton className="aspect-square w-full rounded-2xl" />
        <Skeleton className="mt-4 h-7 w-3/4" />
        <Skeleton className="mt-2 h-5 w-1/3" />
        <Skeleton className="mt-4 h-24 w-full" />
      </ShopLayout>
    );
  }

  if (error || !product) {
    return (
      <ShopLayout settings={settings}>
        <div className="rounded-2xl border border-border bg-card p-6">
          <h1 className="text-xl">No encontramos este producto</h1>
          <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
            {error || 'Puede que ya no esté en el catálogo.'}
          </p>
          <Button asChild className="tap mt-4 rounded-full">
            <Link to="/catalogo">Ver catálogo</Link>
          </Button>
        </div>
      </ShopLayout>
    );
  }

  const agotado = product.available_units <= 0;
  const images = product.images.length > 0 ? product.images : [{ url: product.image_url, alt_text: product.name }];

  return (
    <ShopLayout settings={settings}>
      <Link
        to={product.category_slug ? `/categoria/${product.category_slug}` : '/catalogo'}
        className="tap -ml-2 inline-flex items-center gap-1 pr-3 text-sm font-medium text-muted-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        {product.category_name || 'Catálogo'}
      </Link>

      <div className="mt-2 grid gap-6 lg:grid-cols-2 lg:gap-10">
        <div>
          <div className="overflow-hidden rounded-2xl border border-border bg-muted">
            <img
              src={images[imageIndex].url}
              alt={images[imageIndex].alt_text || product.name}
              width={1024}
              height={1024}
              className="aspect-square w-full object-cover"
            />
          </div>
          {images.length > 1 ? (
            <div className="chips mt-3 flex gap-2 overflow-x-auto">
              {images.map((image, index) => (
                <button
                  key={`${image.url}-${index}`}
                  type="button"
                  onClick={() => setImageIndex(index)}
                  aria-label={`Ver imagen ${index + 1}`}
                  className={`h-16 w-16 flex-shrink-0 overflow-hidden rounded-lg border-2 ${
                    index === imageIndex ? 'border-primary' : 'border-border'
                  }`}
                >
                  <img
                    src={image.url}
                    alt={image.alt_text || product.name}
                    loading="lazy"
                    className="h-full w-full object-cover"
                  />
                </button>
              ))}
            </div>
          ) : null}
        </div>

        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide ${
                agotado
                  ? 'bg-foreground/85 text-background'
                  : product.availability === 'Últimas piezas'
                    ? 'bg-accent text-accent-foreground'
                    : 'bg-secondary text-secondary-foreground'
              }`}
            >
              {product.availability}
            </span>
            {product.tags.map((tag) => (
              <span
                key={tag}
                className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted-foreground"
              >
                {tag}
              </span>
            ))}
          </div>

          <h1 className="mt-3 text-[1.75rem] leading-tight sm:text-3xl">{product.name}</h1>
          <p className="precio mt-2 text-3xl font-bold text-primary">{pesos(unitPrice)}</p>
          <p className="mt-3 max-w-prose text-base leading-relaxed text-muted-foreground">
            {product.short_description}
          </p>

          {/* Variantes; un producto de pieza única tiene una variante sin nombre y no muestra selector. */}
          {product.variants.length > 0 && !product.variants.some((v) => v.option_value) && variant ? (
            <p className="precio mt-4 text-xs text-muted-foreground">
              {variant.available_units > 0
                ? `${variant.available_units} ${variant.available_units === 1 ? 'pieza disponible' : 'piezas disponibles'}`
                : 'Agotado'}
            </p>
          ) : null}
          {product.variants.some((v) => v.option_value) ? (
            <fieldset className="mt-6">
              <legend className="text-sm font-semibold">
                {product.variants[0].option_name || 'Presentación'}
              </legend>
              <div className="mt-2 flex flex-wrap gap-2">
                {product.variants.map((v) => {
                  const sinStock = v.available_units <= 0;
                  const active = v.id === variantId;
                  return (
                    <button
                      key={v.id}
                      type="button"
                      disabled={sinStock}
                      onClick={() => {
                        setVariantId(v.id);
                        setQuantity(1);
                      }}
                      className={`tap flex items-center rounded-full border px-4 text-sm font-medium transition-colors ${
                        active
                          ? 'border-primary bg-accent text-accent-foreground'
                          : 'border-border bg-card text-foreground'
                      } ${sinStock ? 'cursor-not-allowed opacity-45 line-through' : ''}`}
                    >
                      {v.option_value}
                    </button>
                  );
                })}
              </div>
              {variant ? (
                <p className="precio mt-2 text-xs text-muted-foreground">
                  {variant.available_units > 0
                    ? `${variant.available_units} ${variant.available_units === 1 ? 'pieza disponible' : 'piezas disponibles'}`
                    : 'Esta opción está agotada'}
                </p>
              ) : null}
            </fieldset>
          ) : null}

          {/* Cantidad y acción */}
          {!agotado && variant && variant.available_units > 0 ? (
            <div className="mt-6 flex flex-wrap items-center gap-3">
              <div className="flex items-center gap-1 rounded-full border border-border bg-card">
                <button
                  type="button"
                  aria-label="Reducir cantidad"
                  onClick={() => setQuantity((q) => Math.max(1, q - 1))}
                  className="tap rounded-full text-xl leading-none hover:bg-secondary"
                >
                  −
                </button>
                <span className="precio w-8 text-center font-semibold">{quantity}</span>
                <button
                  type="button"
                  aria-label="Aumentar cantidad"
                  disabled={quantity >= maxUnits}
                  onClick={() => setQuantity((q) => Math.min(maxUnits, q + 1))}
                  className="tap rounded-full text-xl leading-none hover:bg-secondary disabled:opacity-40"
                >
                  +
                </button>
              </div>
              <Button onClick={handleAdd} className="tap flex-1 rounded-full text-base sm:flex-none sm:px-8">
                {added ? (
                  <>
                    <Check className="mr-1 h-4 w-4" /> Agregado
                  </>
                ) : (
                  'Apartar este producto'
                )}
              </Button>
            </div>
          ) : (
            <div className="mt-6 rounded-xl border border-border bg-secondary/60 p-4">
              <p className="text-sm font-semibold">Por ahora está agotado</p>
              <p className="mt-1 text-sm leading-relaxed text-muted-foreground">
                Escríbenos por WhatsApp para avisarte cuando vuelva a estar disponible.
              </p>
            </div>
          )}

          <p className="mt-4 rounded-xl border border-border bg-card px-4 py-3 text-sm leading-relaxed">
            {AVISO_SIN_PAGO}
          </p>

          {/* Compartir */}
          <div className="mt-4 flex flex-wrap gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={copyLink}
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
            >
              <Link2 className="mr-2 h-4 w-4" /> Copiar enlace
            </Button>
            <Button
              asChild
              variant="outline"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
            >
              <a
                href={`https://wa.me/?text=${encodeURIComponent(`${product.name} — ${pesos(unitPrice)}\n${shareUrl}`)}`}
                target="_blank"
                rel="noreferrer"
              >
                <MessageCircle className="mr-2 h-4 w-4" /> Compartir por WhatsApp
              </a>
            </Button>
            {settings?.contact_whatsapp ? (
              <Button
                asChild
                variant="ghost"
                className="tap rounded-full text-primary"
              >
                <a
                  href={whatsappLink(
                    settings.contact_whatsapp,
                    `Hola, me interesa ${product.name}. ¿Sigue disponible?`,
                  )}
                  target="_blank"
                  rel="noreferrer"
                >
                  Preguntar por este producto
                </a>
              </Button>
            ) : null}
          </div>

          {/* Detalle */}
          <div className="mt-8 space-y-5">
            {product.full_description ? (
              <section>
                <h2 className="text-lg">Descripción</h2>
                <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {product.full_description}
                </p>
              </section>
            ) : null}
            {product.ingredients ? (
              <section>
                <h2 className="text-lg">Ingredientes y características</h2>
                <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {product.ingredients}
                </p>
              </section>
            ) : null}
            {product.usage_instructions ? (
              <section>
                <h2 className="text-lg">Modo de uso</h2>
                <p className="mt-2 max-w-prose whitespace-pre-line text-sm leading-relaxed text-muted-foreground">
                  {product.usage_instructions}
                </p>
              </section>
            ) : null}
          </div>
        </div>
      </div>

      {data.related.length > 0 ? (
        <section className="mt-12">
          <h2>También te puede gustar</h2>
          <div className="mt-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
            {data.related.map((item) => (
              <ProductCardItem key={item.slug} product={item} />
            ))}
          </div>
        </section>
      ) : null}
    </ShopLayout>
  );
}
