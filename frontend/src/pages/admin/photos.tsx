import { useState } from 'react';
import { ImagePlus, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { apiError, uploadImage } from '@/lib/shop';
import type { CatalogProduct, ToastFn } from './types';

/* ----------------------------- Fotos ----------------------------- */

/** Botón que abre la cámara o la galería y sube las fotos elegidas. */
export function PhotoButton({
  id,
  label,
  multiple = false,
  toast,
  onUploaded,
}: {
  id: string;
  label: string;
  multiple?: boolean;
  toast: ToastFn;
  onUploaded: (urls: string[]) => void;
}) {
  const [uploading, setUploading] = useState(false);

  const handleFiles = async (files: FileList | null) => {
    if (!files || files.length === 0) return;
    setUploading(true);
    const urls: string[] = [];
    try {
      for (const file of Array.from(files)) {
        urls.push(await uploadImage(file));
      }
    } catch (e) {
      toast({ title: apiError(e), variant: 'destructive' });
    } finally {
      setUploading(false);
      if (urls.length > 0) onUploaded(urls);
    }
  };

  return (
    <label
      htmlFor={id}
      className="tap inline-flex cursor-pointer items-center gap-2 rounded-full border border-border px-4 py-2 text-sm font-medium focus-within:ring-2 focus-within:ring-ring"
    >
      {uploading ? <Loader2 className="h-4 w-4 animate-spin" /> : <ImagePlus className="h-4 w-4" />}
      {uploading ? 'Subiendo…' : label}
      <input
        id={id}
        type="file"
        accept="image/*"
        multiple={multiple}
        disabled={uploading}
        className="sr-only"
        onChange={(e) => {
          void handleFiles(e.target.files);
          e.target.value = '';
        }}
      />
    </label>
  );
}

/** Una sola foto: logotipo, portada o imagen de categoría. */
export function PhotoField({
  id,
  label,
  value,
  toast,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  toast: ToastFn;
  onChange: (url: string) => void;
}) {
  return (
    <div>
      <p className="text-sm font-medium">{label}</p>
      <div className="mt-1 flex flex-wrap items-center gap-3">
        {value ? (
          <img src={value} alt="" className="h-16 w-16 rounded-lg border border-border object-cover" />
        ) : null}
        <PhotoButton
          id={id}
          label={value ? 'Cambiar foto' : 'Subir foto'}
          toast={toast}
          onUploaded={(urls) => onChange(urls[0])}
        />
        {value ? (
          <Button
            type="button"
            size="sm"
            variant="ghost"
            className="text-xs text-destructive"
            onClick={() => onChange('')}
          >
            Quitar
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/** Fotos de un producto; la primera es la principal en catálogo y redes. */
export function ProductPhotos({
  images,
  name,
  toast,
  onChange,
}: {
  images: CatalogProduct['images'];
  name: string;
  toast: ToastFn;
  /** Recibe un cambio sobre la lista actual: una subida lenta no deshace lo que se quitó mientras tanto. */
  onChange: (update: (images: CatalogProduct['images']) => CatalogProduct['images']) => void;
}) {
  return (
    <div className="sm:col-span-2">
      <p className="text-sm font-medium">Fotos</p>
      <p className="text-xs text-muted-foreground">La primera foto es la principal.</p>
      <ul className="mt-2 flex flex-wrap gap-3">
        {images.map((image, index) => (
          <li key={`${image.url}-${index}`} className="w-24">
            <img
              src={image.url}
              alt={image.alt_text || name}
              className={`h-24 w-24 rounded-lg object-cover ${index === 0 ? 'ring-2 ring-primary' : 'border border-border'}`}
            />
            <div className="mt-1 flex justify-between">
              {index === 0 ? (
                <span className="text-xs font-semibold text-primary">Principal</span>
              ) : (
                <button
                  type="button"
                  className="text-xs underline"
                  onClick={() => onChange((current) => [image, ...current.filter((i) => i !== image)])}
                >
                  Principal
                </button>
              )}
              <button
                type="button"
                className="text-xs text-destructive underline"
                aria-label={`Quitar foto ${index + 1}`}
                onClick={() => onChange((current) => current.filter((i) => i !== image))}
              >
                Quitar
              </button>
            </div>
          </li>
        ))}
      </ul>
      <div className="mt-2">
        <PhotoButton
          id="p-fotos"
          label="Agregar fotos"
          multiple
          toast={toast}
          onUploaded={(urls) =>
            onChange((current) => [...current, ...urls.map((url) => ({ id: 0, url, alt_text: name }))])
          }
        />
      </div>
    </div>
  );
}
