import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import ShopLayout from '@/components/ShopLayout';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from '@/components/ui/accordion';
import { AVISO_SIN_PAGO, SHOP_NAME_FALLBACK, StoreSettings, api, apiError, setSeo } from '@/lib/shop';

export type ContentKey = 'how_it_works' | 'faq_content' | 'privacy_policy' | 'reservation_policy';

interface ContentResponse {
  shop_name: string;
  how_it_works: string;
  faq_content: string;
  privacy_policy: string;
  reservation_policy: string;
  delivery_instructions: string;
}

interface Bootstrap {
  settings: StoreSettings;
}

const TITULOS: Record<ContentKey, { titulo: string; intro: string; seo: string }> = {
  how_it_works: {
    titulo: 'Cómo funciona',
    intro: 'Apartar es sencillo y no requiere pago dentro del sitio.',
    seo: 'Conoce el proceso de apartado sin anticipo: eliges productos, agendas tu entrega y pagas por transferencia al recibir.',
  },
  faq_content: {
    titulo: 'Preguntas frecuentes',
    intro: 'Las dudas más comunes sobre el apartado y la entrega.',
    seo: 'Respuestas sobre pagos, tiempos de apartado, puntos de entrega y disponibilidad de productos.',
  },
  privacy_policy: {
    titulo: 'Aviso de privacidad',
    intro: 'Cómo tratamos los datos que compartes para coordinar tu entrega.',
    seo: 'Aviso de privacidad sobre el uso de tu nombre, WhatsApp y correo electrónico.',
  },
  reservation_policy: {
    titulo: 'Políticas de apartado',
    intro: 'Reglas claras sobre plazos, vencimientos y entregas.',
    seo: 'Políticas de apartado: plazos de reserva, vencimiento automático, entregas y forma de pago.',
  },
};

function parseFaq(raw: string): { pregunta: string; respuesta: string }[] {
  return raw
    .split('\n')
    .map((line) => line.trim())
    .filter((line) => line.includes('|'))
    .map((line) => {
      const [pregunta, ...resto] = line.split('|');
      return { pregunta: pregunta.trim(), respuesta: resto.join('|').trim() };
    })
    .filter((item) => item.pregunta && item.respuesta);
}

export default function Contenido({ contentKey }: { contentKey: ContentKey }) {
  const [content, setContent] = useState<ContentResponse | null>(null);
  const [settings, setSettings] = useState<StoreSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  const meta = TITULOS[contentKey];

  useEffect(() => {
    api<Bootstrap>('/api/v1/shop/bootstrap')
      .then((result) => setSettings(result.settings))
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api<ContentResponse>('/api/v1/shop/content')
      .then((result) => {
        if (!cancelled) setContent(result);
      })
      .catch((e) => {
        if (!cancelled) setError(apiError(e, 'No pudimos cargar este contenido.'));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [contentKey]);

  useEffect(() => {
    setSeo({
      title: `${meta.titulo} — ${content?.shop_name || settings?.shop_name || SHOP_NAME_FALLBACK}`,
      description: meta.seo,
    });
  }, [meta, content, settings]);

  const raw = content ? content[contentKey] : '';
  const faqItems = contentKey === 'faq_content' ? parseFaq(raw) : [];

  return (
    <ShopLayout settings={settings}>
      <header>
        <h1 className="text-[1.75rem] sm:text-3xl">{meta.titulo}</h1>
        <p className="mt-1 max-w-prose text-sm leading-relaxed text-muted-foreground">{meta.intro}</p>
      </header>

      {loading ? (
        <div className="mt-5 space-y-3">
          <Skeleton className="h-5 w-full" />
          <Skeleton className="h-5 w-11/12" />
          <Skeleton className="h-5 w-4/5" />
          <Skeleton className="h-5 w-full" />
        </div>
      ) : error ? (
        <div className="mt-5 rounded-2xl border border-destructive/40 bg-destructive/10 p-5">
          <h2 className="text-lg">No pudimos cargar este contenido</h2>
          <p className="mt-1 text-sm text-muted-foreground">{error}</p>
          <Button className="tap mt-4 rounded-full" onClick={() => window.location.reload()}>
            Volver a intentar
          </Button>
        </div>
      ) : !raw ? (
        <div className="mt-5 rounded-2xl border border-border bg-card p-5">
          <h2 className="text-lg">Este contenido aún no está publicado</h2>
          <p className="mt-2 max-w-prose text-sm leading-relaxed text-muted-foreground">
            Se puede editar en cualquier momento desde el panel administrativo.
          </p>
          <Button asChild className="tap mt-4 rounded-full">
            <Link to="/catalogo">Ver catálogo</Link>
          </Button>
        </div>
      ) : contentKey === 'faq_content' && faqItems.length > 0 ? (
        <Accordion type="single" collapsible className="mt-5 rounded-2xl border border-border bg-card px-4">
          {faqItems.map((item, index) => (
            <AccordionItem key={item.pregunta} value={`faq-${index}`}>
              <AccordionTrigger className="py-4 text-left text-sm font-semibold">
                {item.pregunta}
              </AccordionTrigger>
              <AccordionContent className="text-sm leading-relaxed text-muted-foreground">
                {item.respuesta}
              </AccordionContent>
            </AccordionItem>
          ))}
        </Accordion>
      ) : (
        <article className="mt-5 rounded-2xl border border-border bg-card p-5">
          <p className="max-w-prose whitespace-pre-line text-sm leading-relaxed text-foreground/90">
            {raw}
          </p>
        </article>
      )}

      <p className="mt-5 rounded-xl border border-primary/30 bg-accent px-4 py-3 text-sm font-medium leading-relaxed text-accent-foreground">
        {AVISO_SIN_PAGO}
      </p>

      <div className="mt-5 flex flex-wrap gap-2">
        <Button asChild className="tap rounded-full">
          <Link to="/catalogo">Ver catálogo</Link>
        </Button>
        {contentKey !== 'faq_content' ? (
          <Button asChild variant="outline" className="tap rounded-full !bg-transparent hover:!bg-transparent">
            <Link to="/preguntas-frecuentes">Preguntas frecuentes</Link>
          </Button>
        ) : null}
        {contentKey !== 'reservation_policy' ? (
          <Button asChild variant="outline" className="tap rounded-full !bg-transparent hover:!bg-transparent">
            <Link to="/politicas-de-apartado">Políticas de apartado</Link>
          </Button>
        ) : null}
      </div>
    </ShopLayout>
  );
}