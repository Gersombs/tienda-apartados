function isIpLiteral(hostname: string): boolean {
  if (hostname.startsWith('[') && hostname.endsWith(']')) return true;
  const parts = hostname.split('.');
  return (
    parts.length === 4 &&
    parts.every((part) => /^\d+$/.test(part) && Number(part) >= 0 && Number(part) <= 255)
  );
}

export function requireCanonicalProductionOrigin(value: string, variableName: string): string {
  if (value !== value.trim()) {
    throw new Error(`${variableName} must not contain surrounding whitespace.`);
  }

  let parsed: URL;
  try {
    parsed = new URL(value);
  } catch {
    throw new Error(`${variableName} must be a valid canonical HTTPS origin.`);
  }

  if (parsed.protocol !== 'https:') {
    throw new Error(`${variableName} must use HTTPS.`);
  }
  if (parsed.username || parsed.password) {
    throw new Error(`${variableName} must not contain credentials.`);
  }
  if (parsed.pathname !== '/' || parsed.search || parsed.hash) {
    throw new Error(`${variableName} must be an origin without path, query, or fragment.`);
  }
  const hostname = parsed.hostname.toLowerCase();
  if (hostname === 'localhost' || hostname.endsWith('.localhost')) {
    throw new Error(`${variableName} cannot use localhost.`);
  }
  if (isIpLiteral(hostname)) {
    throw new Error(`${variableName} must use a DNS hostname, not an IP literal.`);
  }
  if (value !== parsed.origin) {
    throw new Error(
      `${variableName} must use its exact canonical representation without a trailing slash or default port.`,
    );
  }
  return parsed.origin;
}

export function validateReleaseOrigins(
  vitePublicSiteUrl: string,
  backendPublicSiteUrl?: string,
  allowedOrigins?: string,
): string {
  const frontendOrigin = requireCanonicalProductionOrigin(
    vitePublicSiteUrl,
    'VITE_PUBLIC_SITE_URL',
  );
  const hasBackendPublicOrigin = Boolean(backendPublicSiteUrl);
  const hasAllowedOrigins = Boolean(allowedOrigins);
  if (hasBackendPublicOrigin !== hasAllowedOrigins) {
    throw new Error(
      'PUBLIC_SITE_URL and ALLOWED_ORIGINS must both be present for cross-stack release validation.',
    );
  }
  if (!hasBackendPublicOrigin) return frontendOrigin;

  const backendOrigin = requireCanonicalProductionOrigin(
    backendPublicSiteUrl as string,
    'PUBLIC_SITE_URL',
  );
  if ((allowedOrigins as string).includes(',')) {
    throw new Error('ALLOWED_ORIGINS must contain exactly one production origin.');
  }
  const allowedOrigin = requireCanonicalProductionOrigin(
    allowedOrigins as string,
    'ALLOWED_ORIGINS',
  );
  if (frontendOrigin !== backendOrigin || frontendOrigin !== allowedOrigin) {
    throw new Error(
      'VITE_PUBLIC_SITE_URL, PUBLIC_SITE_URL, and ALLOWED_ORIGINS must match exactly.',
    );
  }
  return frontendOrigin;
}
