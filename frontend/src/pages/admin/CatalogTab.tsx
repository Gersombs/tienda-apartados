import { useCallback, useEffect, useMemo, useState } from 'react';
import { RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { confirmAction } from '@/components/ui/confirm-dialog';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import { Skeleton } from '@/components/ui/skeleton';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { api, apiError, pesos } from '@/lib/shop';
import type { CatalogCategory, CatalogProduct, CatalogResponse, ToastFn, VariantRow } from './types';
import { PhotoField, ProductPhotos } from './photos';

/* ---------------------------- Catálogo --------------------------- */
/** "Labial Mate Cereza" -> "labial-mate-cereza", para URLs limpias. */
function slugify(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
}

/** Alta o edición de una variante (tono, tamaño…). El stock inicial sólo se pide al crear. */
export function VariantForm({
  productId,
  productPrice,
  optionName,
  variant,
  toast,
  onDone,
}: {
  productId: number;
  productPrice: number;
  /** Tipo que ya usan las otras variantes del producto, para no volver a escribirlo. */
  optionName: string;
  variant: VariantRow | null;
  toast: ToastFn;
  onDone: (saved: boolean) => void;
}) {
  // Los números se editan como texto: un campo vacío no obliga a borrar un «0».
  const [draft, setDraft] = useState({
    option_name: variant?.option_name ?? optionName,
    option_value: variant?.option_value || '',
    price: variant && variant.price_delta !== 0 ? String(productPrice + variant.price_delta) : '',
    stock: '',
    is_active: variant?.is_active ?? true,
  });
  const [saving, setSaving] = useState(false);
  const prefix = `v-${productId}-${variant?.id ?? 'nueva'}`;
  const hint = 'mt-0.5 text-xs text-muted-foreground';

  const save = async () => {
    if (!draft.option_name.trim() || !draft.option_value.trim()) {
      toast({
        title: 'Escribe qué cambia (por ejemplo «Tono») y el nombre de esta opción.',
        variant: 'destructive',
      });
      return;
    }
    const price = draft.price.trim() === '' ? productPrice : Number(draft.price);
    if (!Number.isFinite(price) || price <= 0) {
      toast({ title: 'El precio debe ser mayor que cero.', variant: 'destructive' });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        product_id: productId,
        option_name: draft.option_name,
        option_value: draft.option_value,
        // El backend guarda la diferencia contra el precio del producto.
        price_delta: Math.round((price - productPrice) * 100) / 100,
        is_active: draft.is_active,
      };
      if (variant) {
        await api(`/api/v1/crm/variants/${variant.id}`, 'PUT', payload);
      } else {
        await api('/api/v1/crm/variants', 'POST', { ...payload, stock: Math.max(0, Number(draft.stock) || 0) });
      }
      toast({ title: variant ? 'Variante actualizada' : 'Variante agregada' });
      onDone(true);
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="mt-2 grid gap-3 rounded-xl border border-primary/40 p-3 sm:grid-cols-2">
      <div>
        <Label htmlFor={`${prefix}-tipo`}>¿Qué cambia entre opciones?</Label>
        <p className={hint}>Por ejemplo: Tono, Tamaño o Aroma. Es el mismo para todas las variantes del producto.</p>
        <Input
          id={`${prefix}-tipo`}
          value={draft.option_name}
          onChange={(e) => setDraft({ ...draft, option_name: e.target.value })}
          className="tap mt-1"
        />
      </div>
      <div>
        <Label htmlFor={`${prefix}-valor`}>Nombre de esta opción</Label>
        <p className={hint}>Por ejemplo: Rojo cereza o 30 ml. Es lo que la clienta elige.</p>
        <Input
          id={`${prefix}-valor`}
          value={draft.option_value}
          onChange={(e) => setDraft({ ...draft, option_value: e.target.value })}
          className="tap mt-1"
        />
      </div>
      <div>
        <Label htmlFor={`${prefix}-precio`}>Precio de esta opción (MXN)</Label>
        <p className={hint}>Déjalo vacío si cuesta lo mismo que el producto ({pesos(productPrice)}).</p>
        <Input
          id={`${prefix}-precio`}
          type="number"
          inputMode="decimal"
          min={0}
          value={draft.price}
          onChange={(e) => setDraft({ ...draft, price: e.target.value })}
          className="precio tap mt-1"
        />
      </div>
      {variant ? null : (
        <div>
          <Label htmlFor={`${prefix}-stock`}>Piezas disponibles</Label>
          <p className={hint}>Cuántas tienes de esta opción. Vacío = 0.</p>
          <Input
            id={`${prefix}-stock`}
            type="number"
            inputMode="numeric"
            min={0}
            value={draft.stock}
            onChange={(e) => setDraft({ ...draft, stock: e.target.value })}
            className="precio tap mt-1"
          />
        </div>
      )}
      <label className="flex items-center gap-2 text-sm sm:col-span-2">
        <input
          type="checkbox"
          checked={draft.is_active}
          onChange={(e) => setDraft({ ...draft, is_active: e.target.checked })}
          className="h-4 w-4 accent-primary"
        />
        Visible en la tienda
      </label>
      <div className="flex gap-2 sm:col-span-2">
        <Button size="sm" className="tap rounded-full" onClick={save} disabled={saving}>
          {saving ? 'Guardando…' : 'Guardar variante'}
        </Button>
        <Button
          size="sm"
          variant="outline"
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
          onClick={() => onDone(false)}
        >
          Cancelar
        </Button>
      </div>
    </div>
  );
}

/** Producto sin tonos ni tamaños: una variante sin nombre guarda sus piezas. */
export function SinglePieceStock({
  productId,
  toast,
  onDone,
}: {
  productId: number;
  toast: ToastFn;
  onDone: () => void;
}) {
  const [stock, setStock] = useState('');
  const [saving, setSaving] = useState(false);
  const save = async () => {
    setSaving(true);
    try {
      await api('/api/v1/crm/variants', 'POST', {
        product_id: productId,
        option_name: '',
        option_value: '',
        stock: Math.max(0, Number(stock) || 0),
        price_delta: 0,
        is_active: true,
      });
      toast({ title: 'Piezas guardadas' });
      onDone();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setSaving(false);
    }
  };
  return (
    <li className="rounded-xl bg-amber-500/10 p-3 text-sm">
      <p className="font-medium text-amber-900">Este producto todavía no se puede apartar.</p>
      <p className="mt-0.5 text-xs text-amber-900/85">
        Si no tiene tonos ni tamaños, sólo indica cuántas piezas tienes. Si los tiene, usa «Agregar variante».
      </p>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <div>
          <Label htmlFor={`unica-${productId}`}>Piezas disponibles</Label>
          <Input
            id={`unica-${productId}`}
            type="number"
            inputMode="numeric"
            min={0}
            value={stock}
            onChange={(e) => setStock(e.target.value)}
            className="precio tap mt-1 w-28"
          />
        </div>
        <Button size="sm" className="tap rounded-full" disabled={saving || !stock} onClick={save}>
          {saving ? 'Guardando…' : 'Guardar piezas'}
        </Button>
      </div>
    </li>
  );
}

/** Categorías del catálogo: alta, edición y borrado. */
export function CategoriesSection({
  categories,
  toast,
  onChanged,
}: {
  categories: CatalogCategory[];
  toast: ToastFn;
  onChanged: () => void;
}) {
  const blank: CatalogCategory = {
    id: 0,
    name: '',
    slug: '',
    description: '',
    image_url: '',
    sort_order: categories.length,
    is_active: true,
  };
  const [editing, setEditing] = useState<CatalogCategory | null>(null);
  const [working, setWorking] = useState(false);

  const save = async () => {
    if (!editing) return;
    const slug = editing.slug || slugify(editing.name);
    if (!editing.name.trim() || !slug) {
      toast({ title: 'Escribe el nombre de la categoría.', variant: 'destructive' });
      return;
    }
    setWorking(true);
    try {
      const payload = {
        name: editing.name,
        slug,
        description: editing.description,
        image_url: editing.image_url,
        sort_order: editing.sort_order,
        is_active: editing.is_active,
      };
      if (editing.id === 0) {
        await api('/api/v1/crm/categories', 'POST', payload);
      } else {
        await api(`/api/v1/crm/categories/${editing.id}`, 'PUT', payload);
      }
      toast({ title: 'Categoría guardada' });
      setEditing(null);
      onChanged();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const remove = async (category: CatalogCategory) => {
    const ok = await confirmAction({
      title: `¿Eliminar la categoría «${category.name}»?`,
      confirmLabel: 'Eliminar',
      destructive: true,
    });
    if (!ok) return;
    setWorking(true);
    try {
      await api(`/api/v1/crm/categories/${category.id}`, 'DELETE');
      toast({ title: 'Categoría eliminada' });
      onChanged();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  return (
    <section className="rounded-2xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base">Categorías</h2>
        <Button size="sm" className="tap rounded-full" onClick={() => setEditing(blank)}>
          Nueva categoría
        </Button>
      </div>
      {categories.length === 0 ? (
        <p className="mt-2 text-sm text-muted-foreground">
          Crea al menos una categoría (por ejemplo «Labios») antes de agregar productos.
        </p>
      ) : (
        <ul className="mt-3 flex flex-wrap gap-2">
          {categories.map((category) => (
            <li key={category.id} className="flex items-center gap-1 rounded-full border border-border pl-3">
              <span className="text-sm">
                {category.name}
                {category.is_active ? '' : ' (oculta)'}
              </span>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs"
                onClick={() => setEditing(category)}
              >
                Editar
              </Button>
              <Button
                size="sm"
                variant="ghost"
                className="text-xs text-destructive"
                disabled={working}
                onClick={() => remove(category)}
              >
                Eliminar
              </Button>
            </li>
          ))}
        </ul>
      )}
      {editing ? (
        <div className="mt-3 grid gap-3 rounded-xl border border-primary/40 p-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="c-nombre">Nombre</Label>
            <Input
              id="c-nombre"
              value={editing.name}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  name: e.target.value,
                  slug:
                    editing.id === 0 && editing.slug === slugify(editing.name)
                      ? slugify(e.target.value)
                      : editing.slug,
                })
              }
              className="tap mt-1"
            />
          </div>
          <div>
            <Label htmlFor="c-desc">Descripción corta</Label>
            <Input
              id="c-desc"
              value={editing.description}
              onChange={(e) => setEditing({ ...editing, description: e.target.value })}
              className="tap mt-1"
            />
          </div>
          <PhotoField
            id="c-foto"
            label="Foto de la categoría"
            value={editing.image_url}
            toast={toast}
            onChange={(url) => setEditing((current) => (current ? { ...current, image_url: url } : current))}
          />
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={editing.is_active}
              onChange={(e) => setEditing({ ...editing, is_active: e.target.checked })}
              className="h-4 w-4 accent-primary"
            />
            Visible en la tienda
          </label>
          <div className="flex gap-2 sm:col-span-2">
            <Button size="sm" className="tap rounded-full" onClick={save} disabled={working}>
              Guardar categoría
            </Button>
            <Button
              size="sm"
              variant="outline"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
              onClick={() => setEditing(null)}
            >
              Cancelar
            </Button>
          </div>
        </div>
      ) : null}
    </section>
  );
}

export function CatalogTab({ toast }: { toast: ToastFn }) {
  const [data, setData] = useState<CatalogResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [editing, setEditing] = useState<CatalogProduct | null>(null);
  const [working, setWorking] = useState(false);
  const [stockDrafts, setStockDrafts] = useState<Record<number, string>>({});
  // Variante abierta en el formulario: variant null = nueva.
  const [variantForm, setVariantForm] = useState<{ productId: number; variant: VariantRow | null } | null>(
    null,
  );

  const load = useCallback(() => {
    setLoading(true);
    api<CatalogResponse>('/api/v1/crm/catalog')
      .then(setData)
      .catch((e) => toast({ title: apiError(e), variant: 'destructive' }))
      .finally(() => setLoading(false));
  }, [toast]);

  useEffect(load, [load]);

  const blank: CatalogProduct = useMemo(
    () => ({
      id: 0,
      name: '',
      slug: '',
      short_description: '',
      full_description: '',
      ingredients: '',
      usage_instructions: '',
      category_id: data?.categories[0]?.id ?? null,
      price: 0,
      tags: '',
      is_active: true,
      is_featured: false,
      is_archived: false,
      sort_order: 0,
      images: [],
      variants: [],
    }),
    [data],
  );

  const saveProduct = async () => {
    if (!editing) return;
    if (!editing.name.trim() || !editing.slug.trim() || editing.price <= 0) {
      toast({ title: 'Nombre, dirección (URL) y precio son obligatorios.', variant: 'destructive' });
      return;
    }
    setWorking(true);
    try {
      const payload = {
        name: editing.name,
        slug: editing.slug,
        short_description: editing.short_description,
        full_description: editing.full_description,
        ingredients: editing.ingredients,
        usage_instructions: editing.usage_instructions,
        category_id: editing.category_id,
        price: editing.price,
        tags: editing.tags,
        is_active: editing.is_active,
        is_featured: editing.is_featured,
        is_archived: editing.is_archived,
        sort_order: editing.sort_order,
        images: editing.images.map((i) => i.url).filter(Boolean),
      };
      if (editing.id === 0) {
        await api('/api/v1/crm/products', 'POST', payload);
      } else {
        await api(`/api/v1/crm/products/${editing.id}`, 'PUT', payload);
      }
      toast({ title: 'Producto guardado' });
      setEditing(null);
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const adjustStock = async (variantId: number) => {
    const raw = stockDrafts[variantId];
    if (raw === undefined || raw === '') return;
    setWorking(true);
    try {
      await api('/api/v1/crm/stock-adjust', 'POST', {
        variant_id: variantId,
        new_stock: Number(raw),
        note: 'Ajuste manual desde el catálogo',
      });
      toast({ title: 'Inventario actualizado' });
      setStockDrafts((prev) => ({ ...prev, [variantId]: '' }));
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const removeVariant = async (variant: VariantRow) => {
    const ok = await confirmAction({
      title: `¿Eliminar la variante «${variant.label || 'Pieza única'}»?`,
      confirmLabel: 'Eliminar',
      destructive: true,
    });
    if (!ok) return;
    setWorking(true);
    try {
      await api(`/api/v1/crm/variants/${variant.id}`, 'DELETE');
      toast({ title: 'Variante eliminada' });
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  const removeProduct = async (product: CatalogProduct) => {
    const ok = await confirmAction({
      title: `¿Eliminar «${product.name}»?`,
      description: 'Si sólo quieres ocultarlo de la tienda, márcalo como «Archivado».',
      confirmLabel: 'Eliminar',
      destructive: true,
    });
    if (!ok) return;
    setWorking(true);
    try {
      await api(`/api/v1/crm/products/${product.id}`, 'DELETE');
      toast({ title: 'Producto eliminado' });
      load();
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setWorking(false);
    }
  };

  if (loading || !data) {
    return (
      <div className="space-y-2">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} className="h-24 rounded-2xl" />
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Button className="tap rounded-full" onClick={() => setEditing(blank)}>
          Nuevo producto
        </Button>
        <Button
          variant="outline"
          className="tap rounded-full !bg-transparent hover:!bg-transparent"
          onClick={load}
        >
          <RefreshCw className="mr-2 h-4 w-4" /> Actualizar
        </Button>
        <span className="precio text-sm text-muted-foreground">
          {data.products.length} productos · {data.categories.length} categorías
        </span>
      </div>

      <CategoriesSection categories={data.categories} toast={toast} onChanged={load} />

      {editing ? (
        <section className="rounded-2xl border border-primary/40 bg-card p-4">
          <h2 className="text-base">{editing.id === 0 ? 'Nuevo producto' : `Editar: ${editing.name}`}</h2>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div>
              <Label htmlFor="p-nombre">Nombre</Label>
              <Input
                id="p-nombre"
                value={editing.name}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    name: e.target.value,
                    // En productos nuevos la URL sigue al nombre mientras no se edite a mano.
                    slug:
                      editing.id === 0 && editing.slug === slugify(editing.name)
                        ? slugify(e.target.value)
                        : editing.slug,
                  })
                }
                className="tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-slug">Dirección del producto (URL)</Label>
              <Input
                id="p-slug"
                value={editing.slug}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    slug: e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, '-'),
                  })
                }
                className="tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-precio">Precio MXN</Label>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Precio normal. Si un tono o tamaño cuesta distinto, lo indicas en esa variante.
              </p>
              <Input
                id="p-precio"
                type="number"
                min={0}
                inputMode="decimal"
                value={editing.price || ''}
                onChange={(e) => setEditing({ ...editing, price: Number(e.target.value) })}
                className="precio tap mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-categoria">Categoría</Label>
              <Select
                value={editing.category_id ? String(editing.category_id) : ''}
                onValueChange={(value) => setEditing({ ...editing, category_id: Number(value) })}
              >
                <SelectTrigger id="p-categoria" className="tap mt-1">
                  <SelectValue placeholder="Selecciona" />
                </SelectTrigger>
                <SelectContent>
                  {data.categories.map((c) => (
                    <SelectItem key={c.id} value={String(c.id)}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-corta">Descripción corta</Label>
              <Input
                id="p-corta"
                value={editing.short_description}
                onChange={(e) => setEditing({ ...editing, short_description: e.target.value })}
                className="tap mt-1"
              />
            </div>
            <div className="sm:col-span-2">
              <Label htmlFor="p-larga">Descripción completa</Label>
              <Textarea
                id="p-larga"
                rows={4}
                value={editing.full_description}
                onChange={(e) => setEditing({ ...editing, full_description: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-ing">Ingredientes</Label>
              <Textarea
                id="p-ing"
                rows={3}
                value={editing.ingredients}
                onChange={(e) => setEditing({ ...editing, ingredients: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-uso">Modo de uso</Label>
              <Textarea
                id="p-uso"
                rows={3}
                value={editing.usage_instructions}
                onChange={(e) => setEditing({ ...editing, usage_instructions: e.target.value })}
                className="mt-1"
              />
            </div>
            <div>
              <Label htmlFor="p-tags">Etiquetas (separadas por coma)</Label>
              <Input
                id="p-tags"
                value={editing.tags}
                onChange={(e) => setEditing({ ...editing, tags: e.target.value })}
                className="tap mt-1"
              />
            </div>
            <ProductPhotos
              images={editing.images}
              name={editing.name}
              toast={toast}
              onChange={(update) =>
                setEditing((current) => (current ? { ...current, images: update(current.images) } : current))
              }
            />
          </div>

          <div className="mt-3 flex flex-wrap gap-4">
            {(
              [
                ['is_active', 'Visible en la tienda'],
                ['is_featured', 'Destacado en inicio'],
                ['is_archived', 'Archivado'],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={Boolean(editing[key])}
                  onChange={(e) => setEditing({ ...editing, [key]: e.target.checked })}
                  className="h-4 w-4 accent-primary"
                />
                {label}
              </label>
            ))}
          </div>

          <div className="mt-4 flex gap-2">
            <Button className="tap rounded-full" onClick={saveProduct} disabled={working}>
              {working ? 'Guardando…' : 'Guardar producto'}
            </Button>
            <Button
              variant="outline"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
              onClick={() => setEditing(null)}
            >
              Cancelar
            </Button>
          </div>
        </section>
      ) : null}

      <div className="space-y-3">
        {data.products.map((product) => (
          <section key={product.id} className="rounded-2xl border border-border bg-card p-4">
            <div className="flex items-start gap-3">
              {product.images[0] ? (
                <img
                  src={product.images[0].url}
                  alt={product.name}
                  loading="lazy"
                  className="h-16 w-16 flex-shrink-0 rounded-lg object-cover"
                />
              ) : null}
              <div className="min-w-0 flex-1">
                <p className="text-sm font-semibold">{product.name}</p>
                <p className="precio text-xs text-muted-foreground">
                  {pesos(product.price)} ·{' '}
                  {product.variants.length === 1 && !product.variants[0].option_value
                    ? 'pieza única'
                    : `${product.variants.length} ${product.variants.length === 1 ? 'variante' : 'variantes'}`}
                  {product.is_featured ? ' · destacado' : ''}
                  {!product.is_active ? ' · oculto' : ''}
                  {product.is_archived ? ' · archivado' : ''}
                </p>
              </div>
              <div className="flex flex-shrink-0 flex-col gap-1">
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-full !bg-transparent text-xs hover:!bg-transparent"
                  onClick={() => setEditing(product)}
                >
                  Editar
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  className="text-xs text-destructive"
                  disabled={working}
                  onClick={() => removeProduct(product)}
                >
                  Eliminar
                </Button>
              </div>
            </div>

            <ul className="mt-3 space-y-2 border-t border-border pt-3">
              {product.variants.map((variant) => (
                <li key={variant.id} className="rounded-lg border border-border p-2.5 text-sm">
                  <div className="flex flex-wrap items-baseline justify-between gap-x-2">
                    <span className="font-medium">{variant.label || 'Pieza única'}</span>
                    <span className="precio text-xs text-muted-foreground">
                      {variant.available_units} libres de {variant.stock}
                      {variant.reserved_stock > 0 ? ` · ${variant.reserved_stock} apartadas` : ''}
                    </span>
                  </div>
                  <div className="mt-2 flex flex-wrap items-end gap-2">
                    <div>
                      <Label htmlFor={`stock-${variant.id}`} className="text-xs text-muted-foreground">
                        Nuevo total de piezas
                      </Label>
                      <Input
                        id={`stock-${variant.id}`}
                        type="number"
                        inputMode="numeric"
                        min={0}
                        value={stockDrafts[variant.id] ?? ''}
                        onChange={(e) =>
                          setStockDrafts((prev) => ({ ...prev, [variant.id]: e.target.value }))
                        }
                        className="precio mt-1 h-10 w-24"
                      />
                    </div>
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={working || !stockDrafts[variant.id]}
                      onClick={() => adjustStock(variant.id)}
                      className="tap rounded-full !bg-transparent text-xs hover:!bg-transparent"
                    >
                      Ajustar
                    </Button>
                    {/* Una pieza única sólo tiene inventario; no hay nombre que editar. */}
                    {variant.option_value ? (
                      <Button
                        size="sm"
                        variant="ghost"
                        className="tap text-xs"
                        onClick={() => setVariantForm({ productId: product.id, variant })}
                      >
                        Editar
                      </Button>
                    ) : null}
                    <Button
                      size="sm"
                      variant="ghost"
                      className="tap text-xs text-destructive"
                      disabled={working}
                      onClick={() => removeVariant(variant)}
                    >
                      Eliminar
                    </Button>
                  </div>
                </li>
              ))}
              {product.variants.length === 0 ? (
                <SinglePieceStock productId={product.id} toast={toast} onDone={load} />
              ) : null}
            </ul>
            {variantForm?.productId === product.id ? (
              <VariantForm
                key={variantForm.variant?.id ?? 'nueva'}
                productId={product.id}
                productPrice={product.price}
                optionName={product.variants.find((v) => v.option_name)?.option_name ?? ''}
                variant={variantForm.variant}
                toast={toast}
                onDone={(saved) => {
                  setVariantForm(null);
                  if (saved) load();
                }}
              />
            ) : product.variants.some((v) => !v.option_value) ? (
              <p className="mt-2 text-xs text-muted-foreground">
                Para usar tonos o tamaños, primero elimina la pieza única.
              </p>
            ) : (
              <Button
                size="sm"
                variant="outline"
                className="mt-2 rounded-full !bg-transparent text-xs hover:!bg-transparent"
                onClick={() => setVariantForm({ productId: product.id, variant: null })}
              >
                Agregar variante
              </Button>
            )}
          </section>
        ))}
      </div>
    </div>
  );
}
