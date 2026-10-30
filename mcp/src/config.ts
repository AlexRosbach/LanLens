import { isIP } from 'node:net';

export type TransportMode = 'stdio' | 'http';

export interface LanLensMcpConfig {
  lanlensUrl: string;
  apiToken: string;
  enableWrites: boolean;
  requestTimeoutMs: number;
  transport: TransportMode;
  host: string;
  port: number;
  httpToken?: string;
  allowedHosts: string[];
}

const LOOPBACK_HOSTS = new Set(['127.0.0.1', '::1', 'localhost']);

function parseBoolean(value: string | undefined, fallback = false): boolean {
  if (value === undefined || value === '') return fallback;
  return ['1', 'true', 'yes', 'on'].includes(value.toLowerCase());
}

function parseInteger(value: string | undefined, fallback: number, minimum: number, maximum: number): number {
  if (!value) return fallback;
  const parsed = Number.parseInt(value, 10);
  if (!Number.isSafeInteger(parsed) || parsed < minimum || parsed > maximum) {
    throw new Error(`Expected an integer between ${minimum} and ${maximum}`);
  }
  return parsed;
}

function normalizeLanLensUrl(raw: string): string {
  const parsed = new URL(raw);
  if (!['http:', 'https:'].includes(parsed.protocol)) {
    throw new Error('LANLENS_URL must use http or https');
  }
  if (parsed.username || parsed.password || parsed.search || parsed.hash) {
    throw new Error('LANLENS_URL must not contain credentials, query parameters, or a fragment');
  }
  parsed.pathname = parsed.pathname.replace(/\/+$/, '');
  return parsed.toString().replace(/\/$/, '');
}

function isLoopback(host: string): boolean {
  if (LOOPBACK_HOSTS.has(host.toLowerCase())) return true;
  return isIP(host) === 4 && host.startsWith('127.');
}

export function loadConfig(argv = process.argv.slice(2), env = process.env): LanLensMcpConfig {
  const transportArg = argv.find((arg) => arg.startsWith('--transport='))?.split('=', 2)[1];
  const transport = (transportArg ?? env.LANLENS_MCP_TRANSPORT ?? 'stdio') as TransportMode;
  if (!['stdio', 'http'].includes(transport)) {
    throw new Error('Transport must be stdio or http');
  }

  const lanlensUrl = normalizeLanLensUrl(env.LANLENS_URL ?? 'http://127.0.0.1:7765');
  const apiToken = env.LANLENS_API_TOKEN?.trim() ?? '';
  if (apiToken.length < 32) {
    throw new Error('LANLENS_API_TOKEN must contain the configured persistent token (minimum 32 characters)');
  }

  const host = env.LANLENS_MCP_HOST?.trim() || '127.0.0.1';
  const httpToken = env.LANLENS_MCP_HTTP_TOKEN?.trim() || undefined;
  if (transport === 'http' && !isLoopback(host) && (!httpToken || httpToken.length < 32)) {
    throw new Error('LANLENS_MCP_HTTP_TOKEN with at least 32 characters is required for a non-loopback HTTP bind');
  }

  const defaultAllowedHosts = isLoopback(host)
    ? ['localhost', '127.0.0.1', '[::1]']
    : [];
  const allowedHosts = (env.LANLENS_MCP_ALLOWED_HOSTS?.split(',') ?? defaultAllowedHosts)
    .map((value) => value.trim())
    .filter(Boolean);
  if (transport === 'http' && allowedHosts.length === 0) {
    throw new Error('LANLENS_MCP_ALLOWED_HOSTS is required for a non-loopback HTTP bind');
  }

  return {
    lanlensUrl,
    apiToken,
    enableWrites: parseBoolean(env.LANLENS_MCP_ENABLE_WRITES),
    requestTimeoutMs: parseInteger(env.LANLENS_MCP_TIMEOUT_MS, 15_000, 1_000, 60_000),
    transport,
    host,
    port: parseInteger(env.LANLENS_MCP_PORT, 8787, 1, 65_535),
    httpToken,
    allowedHosts,
  };
}

export function isLoopbackHost(host: string): boolean {
  return isLoopback(host);
}
