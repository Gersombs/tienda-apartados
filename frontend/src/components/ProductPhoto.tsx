import { cn } from '@/lib/utils';

/** Foto del producto; sin foto muestra su inicial en vez del icono de imagen rota. */
export default function ProductPhoto({
  src,
  alt,
  name,
  className,
  ...rest
}: React.ImgHTMLAttributes<HTMLImageElement> & { name: string }) {
  if (src) return <img src={src} alt={alt} className={className} {...rest} />;
  return (
    <div
      // alt="" = decorativa, igual que en una <img>: el nombre ya está escrito al lado.
      {...(alt === '' ? { 'aria-hidden': true } : { role: 'img', 'aria-label': alt || name })}
      className={cn('flex items-center justify-center text-4xl text-primary/70', className, 'bg-accent/60')}
    >
      <span className="display font-semibold leading-none">{name.trim().charAt(0).toUpperCase()}</span>
    </div>
  );
}
