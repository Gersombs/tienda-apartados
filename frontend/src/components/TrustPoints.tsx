import { Handshake, ShieldCheck, Wallet } from 'lucide-react';
import { AVISO_SIN_PAGO } from '@/lib/shop';

const CONFIANZA = [
  { icon: ShieldCheck, texto: 'Sin anticipo' },
  { icon: Handshake, texto: 'Entrega en persona' },
  { icon: Wallet, texto: 'Pagas al recibir' },
];

/** Las tres promesas del apartado y el aviso de que en el sitio no se paga nada. */
export default function TrustPoints({ className = '' }: { className?: string }) {
  return (
    <div className={className}>
      <ul className="flex flex-wrap gap-x-5 gap-y-2 text-base font-medium">
        {CONFIANZA.map(({ icon: Icon, texto }) => (
          <li key={texto} className="flex items-center gap-1.5">
            <Icon className="h-4 w-4 text-primary" /> {texto}
          </li>
        ))}
      </ul>
      <p className="mt-3 text-base leading-relaxed text-foreground/80">{AVISO_SIN_PAGO}</p>
    </div>
  );
}
