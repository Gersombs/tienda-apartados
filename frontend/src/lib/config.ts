const configuredBase = (import.meta.env.VITE_API_BASE_URL || '').trim().replace(/\/$/, '');

export function getAPIBaseURL(): string {
  if (
    configuredBase &&
    typeof window !== 'undefined' &&
    new URL(configuredBase, window.location.origin).origin !== window.location.origin
  ) {
    throw new Error('La API debe compartir el origen del frontend para que CSRF funcione.');
  }
  return configuredBase;
}
