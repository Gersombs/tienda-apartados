import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';
import {
  requireCanonicalProductionOrigin,
  validateReleaseOrigins,
} from '../origin-validation.ts';


const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(resolve(root, path), 'utf8');


test('production origin validator accepts only an exact canonical DNS origin', () => {
  assert.equal(
    requireCanonicalProductionOrigin('https://staging.example.com', 'TEST_ORIGIN'),
    'https://staging.example.com',
  );
  const invalidOrigins = [
    'http://staging.example.com',
    'https://staging.example.com/',
    'https://staging.example.com/path',
    'https://user:password@staging.example.com',
    'https://staging.example.com?preview=1',
    'https://staging.example.com#fragment',
    'https://staging.example.com:443',
    'https://localhost',
    'https://sub.localhost',
    'https://127.0.0.1',
    'https://10.0.0.1',
    'https://8.8.8.8',
    ' https://staging.example.com',
  ];
  for (const origin of invalidOrigins) {
    assert.throws(() => requireCanonicalProductionOrigin(origin, 'TEST_ORIGIN'));
  }
});


test('release origin validator checks all cross-stack values when supplied', () => {
  assert.equal(
    validateReleaseOrigins(
      'https://staging.example.com',
      'https://staging.example.com',
      'https://staging.example.com',
    ),
    'https://staging.example.com',
  );
  assert.throws(() =>
    validateReleaseOrigins(
      'https://staging.example.com',
      'https://other.example.com',
      'https://staging.example.com',
    ),
  );
  assert.throws(() =>
    validateReleaseOrigins(
      'https://staging.example.com',
      'https://staging.example.com',
      'https://staging.example.com,https://api.example.com',
    ),
  );
  assert.throws(() =>
    validateReleaseOrigins('https://staging.example.com', 'https://staging.example.com'),
  );
});


test('package exposes reproducible quality commands and pinned toolchain', () => {
  const pkg = JSON.parse(read('package.json'));
  assert.equal(pkg.packageManager, 'pnpm@11.22.0');
  for (const script of ['lint', 'typecheck', 'test', 'build']) assert.ok(pkg.scripts[script]);
  assert.equal(pkg.dependencies['@metagptx/web-sdk'], undefined);
  assert.equal(pkg.dependencies.axios, undefined);
});


test('admin uses local cookie session, handles expiry and has no claim flow', () => {
  const admin = read('src/pages/Admin.tsx');
  const api = read('src/lib/shop.ts');
  assert.match(admin, /\/api\/v1\/auth\/login/);
  assert.match(admin, /type="password"/);
  assert.doesNotMatch(admin, /claim-admin|client\.auth|localStorage/);
  assert.match(admin, /Enviar enlace nuevo a la clienta/);
  assert.match(admin, /rotate-confirmation-token/);
  assert.match(admin, /revoke-confirmation-token/);
  assert.match(admin, /confirmAction\(/);
  assert.doesNotMatch(admin, /window\.confirm/);
  assert.match(admin, /navigator\.clipboard\.writeText/);
  assert.match(admin, /\/confirmacion#t=/);
  assert.doesNotMatch(admin, /confirmacion\?t=/);
  assert.match(api, /credentials: 'include'/);
  assert.match(api, /X-CSRF-Token/);
  assert.match(api, /admin-session-expired/);
});


test('confirmation is token-based and marked noindex', () => {
  const confirmation = read('src/pages/Confirmacion.tsx');
  const apartado = read('src/pages/Apartado.tsx');
  assert.match(confirmation, /window\.location\.hash/);
  assert.match(confirmation, /\/api\/v1\/shop\/confirmation/);
  assert.match(confirmation, /'POST'/);
  assert.doesNotMatch(confirmation, /useSearchParams|searchParams\.get\('t'\)/);
  assert.match(apartado, /\/confirmacion#t=/);
  assert.doesNotMatch(apartado, /\/confirmacion\?t=/);
  assert.match(confirmation, /noindex: true/);
  assert.doesNotMatch(confirmation, /\/reservations\/\$\{.*id/);
});


test('brand, payment wording and static SEO are consistent', () => {
  const html = read('index.html');
  const home = read('src/pages/Index.tsx');
  const shop = read('src/lib/shop.ts');
  assert.match(html, /<html lang="es-MX">/);
  assert.match(html, /Nébula Beauty MX/);
  assert.match(html, /rel="canonical"/);
  assert.match(html, /\/\(admin\|confirmacion\)/);
  const obsoleteTemplateDomain = [["at", "oms"].join(''), 'template', 'com'].join('\\.');
  const retiredMarketBrand = [['Mer', 'cado'].join(''), ['Mó', 'vil'].join('')].join('');
  assert.doesNotMatch(`${html}\n${home}`, new RegExp(`${retiredMarketBrand}|${obsoleteTemplateDomain}|Compra por categoría`, 'i'));
  assert.match(shop, /No pagarás nada en este sitio/);
});


test('sitemap is environment-based and excludes all private routes', () => {
  const vite = read('vite.config.ts');
  const runtimeConfig = read('src/lib/config.ts');
  const exampleEnv = read('.env.example');
  const dynamicRoutes = vite.match(/dynamicRoutes:\s*\[([\s\S]*?)\]/)?.[1] ?? '';
  assert.match(vite, /VITE_PUBLIC_SITE_URL/);
  assert.match(vite, /VITE_API_BASE_URL must be empty/);
  assert.match(vite, /apiOrigin !== frontendOrigin/);
  assert.match(runtimeConfig, /window\.location\.origin/);
  assert.match(exampleEnv, /^VITE_API_BASE_URL=\r?$/m);
  assert.ok(!vite.includes([["at", "oms"].join(''), 'template', 'com'].join('.')));
  for (const route of ['/admin', '/confirmacion', '/apartado', '/auth/']) assert.ok(vite.includes(route));
  assert.doesNotMatch(dynamicRoutes, /['"]\/admin['"]/);
});


test('no functional online-payment or legacy generated API code remains', () => {
  const sources = [
    read('src/App.tsx'),
    read('src/lib/shop.ts'),
    read('src/pages/Admin.tsx'),
    read('src/pages/Apartado.tsx'),
    read('vite.config.ts'),
    read('package.json'),
  ].join('\n');
  const retiredSignals = [
    ['str', 'ipe'].join(''),
    ['payment', '_intent'].join(''),
    ['check', 'out'].join(''),
    ['/api/v1/', ['enti', 'ties/'].join('')].join(''),
  ];
  for (const signal of retiredSignals) assert.doesNotMatch(sources, new RegExp(signal, 'i'));
});
