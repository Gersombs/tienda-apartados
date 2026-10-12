import { useEffect, useRef, useState } from 'react';
import { Button } from '@/components/ui/button';

interface ConfirmOptions {
  title: string;
  description?: string;
  confirmLabel?: string;
  destructive?: boolean;
}

type Pending = ConfirmOptions & { resolve: (ok: boolean) => void };

let openDialog: ((pending: Pending) => void) | null = null;

/** Reemplazo de window.confirm con el estilo de la tienda. Requiere <ConfirmDialogHost /> montado. */
export function confirmAction(options: ConfirmOptions): Promise<boolean> {
  return new Promise((resolve) => {
    if (!openDialog) {
      resolve(window.confirm(options.title));
      return;
    }
    openDialog({ ...options, resolve });
  });
}

export function ConfirmDialogHost() {
  const [pending, setPending] = useState<Pending | null>(null);
  const ref = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    openDialog = setPending;
    return () => {
      openDialog = null;
    };
  }, []);

  useEffect(() => {
    // showModal da foco atrapado, Escape y fondo bloqueado sin código extra.
    if (pending && !ref.current?.open) ref.current?.showModal();
  }, [pending]);

  const close = (ok: boolean) => {
    pending?.resolve(ok);
    setPending(null);
    ref.current?.close();
  };

  return (
    <dialog
      ref={ref}
      aria-labelledby="confirm-title"
      onCancel={(e) => {
        e.preventDefault();
        close(false);
      }}
      className="w-[calc(100%-2rem)] max-w-sm rounded-2xl border border-border bg-card p-5 text-foreground shadow-xl backdrop:bg-black/40"
    >
      {pending ? (
        <>
          <h2 id="confirm-title" className="text-lg">
            {pending.title}
          </h2>
          {pending.description ? (
            <p className="mt-2 text-sm leading-relaxed text-muted-foreground">{pending.description}</p>
          ) : null}
          <div className="mt-5 flex flex-wrap justify-end gap-2">
            <Button
              autoFocus
              variant="outline"
              className="tap rounded-full !bg-transparent hover:!bg-transparent"
              onClick={() => close(false)}
            >
              Cancelar
            </Button>
            <Button
              variant={pending.destructive ? 'destructive' : 'default'}
              className="tap rounded-full"
              onClick={() => close(true)}
            >
              {pending.confirmLabel || 'Continuar'}
            </Button>
          </div>
        </>
      ) : null}
    </dialog>
  );
}
