import { Link } from 'react-router-dom';
import { ProductCard, pesos } from '@/lib/shop';

const BADGE_STYLES: Record<string, string> = {
  Disponible: 'bg-secondary text-secondary-foreground',
  'Últimas piezas': 'bg-accent text-accent-foreground',
  Agotado: 'bg-foreground/85 text-background',
};

export default function ProductCardItem({ product }: { product: ProductCard }) {
  const agotado = product.available_units <= 0;

  return (
    <Link
      to={`/producto/${product.slug}`}
      className="group flex flex-col overflow-hidden rounded-2xl border border-border bg-card transition-colors hover:md:border-primary/50"
    >
      <div className="relative aspect-square overflow-hidden bg-muted">
        <img
          src={product.image_url}
          alt={product.image_alt}
          loading="lazy"
          width={512}
          height={512}
          className={`h-full w-full object-cover transition-transform duration-500 ${
            agotado ? 'opacity-70' : 'group-hover:md:scale-[1.04]'
          }`}
        />
        <span
          className={`absolute left-2 top-2 rounded-full px-2.5 py-1 text-[11px] font-semibold tracking-wide ${
            BADGE_STYLES[product.availability] || BADGE_STYLES.Disponible
          }`}
        >
          {product.availability}
        </span>
      </div>

      <div className="flex flex-1 flex-col gap-1 p-3">
        {product.category_name ? (
          <p className="text-[11px] font-semibold uppercase tracking-wider text-primary">
            {product.category_name}
          </p>
        ) : null}
        <h3 className="line-clamp-2 text-sm font-semibold leading-snug">{product.name}</h3>
        <p className="line-clamp-2 text-xs leading-relaxed text-muted-foreground">
          {product.short_description}
        </p>
        <p className="precio mt-auto pt-2 text-base font-bold">{pesos(product.price)}</p>
      </div>
    </Link>
  );
}