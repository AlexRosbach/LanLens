import type { LanLensMcpConfig } from './config.js';

const MAX_RESPONSE_BYTES = 8 * 1024 * 1024;

export class LanLensApiError extends Error {
  constructor(
    message: string,
    public readonly status?: number,
    public readonly code = 'LANLENS_API_ERROR',
  ) {
    super(message);
    this.name = 'LanLensApiError';
  }
}

export class LanLensClient {
  constructor(private readonly config: Pick<LanLensMcpConfig, 'lanlensUrl' | 'apiToken' | 'requestTimeoutMs'>) {}

  private async request(method: 'GET' | 'PUT', path: string, body?: Record<string, unknown>): Promise<unknown> {
    const url = new URL(path, `${this.config.lanlensUrl}/`);
    if (url.origin !== new URL(this.config.lanlensUrl).origin) {
      throw new LanLensApiError('Refusing a request outside the configured LanLens origin', undefined, 'INVALID_TARGET');
    }

    let response: Response;
    try {
      response = await fetch(url, {
        method,
        redirect: 'error',
        signal: AbortSignal.timeout(this.config.requestTimeoutMs),
        headers: {
          accept: 'application/json',
          authorization: `Bearer ${this.config.apiToken}`,
          ...(body ? {'content-type': 'application/json'} : {}),
        },
        ...(body ? {body: JSON.stringify(body)} : {}),
      });
    } catch (error) {
      if (error instanceof DOMException && error.name === 'TimeoutError') {
        throw new LanLensApiError('LanLens request timed out', undefined, 'TIMEOUT');
      }
      throw new LanLensApiError('LanLens is unreachable or rejected the connection', undefined, 'UNREACHABLE');
    }

    const contentLength = Number(response.headers.get('content-length') ?? '0');
    if (contentLength > MAX_RESPONSE_BYTES) {
      throw new LanLensApiError('LanLens response exceeded the MCP size limit', response.status, 'RESPONSE_TOO_LARGE');
    }
    const text = await response.text();
    if (Buffer.byteLength(text) > MAX_RESPONSE_BYTES) {
      throw new LanLensApiError('LanLens response exceeded the MCP size limit', response.status, 'RESPONSE_TOO_LARGE');
    }

    let payload: unknown = null;
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch {
        throw new LanLensApiError('LanLens returned an invalid JSON response', response.status, 'INVALID_RESPONSE');
      }
    }

    if (!response.ok) {
      const detail = payload && typeof payload === 'object' && 'detail' in payload
        ? String((payload as {detail: unknown}).detail)
        : `HTTP ${response.status}`;
      throw new LanLensApiError(`LanLens request failed: ${detail}`, response.status,
        response.status === 401 ? 'UNAUTHENTICATED' : response.status === 403 ? 'FORBIDDEN' : 'HTTP_ERROR');
    }
    return payload;
  }

  health(): Promise<unknown> {
    return this.request('GET', '/api/health');
  }

  listDevices(filters: {
    onlineOnly?: boolean;
    unregisteredOnly?: boolean;
    deviceClass?: string;
    search?: string;
    archivedOnly?: boolean;
  }): Promise<unknown> {
    const query = new URLSearchParams();
    if (filters.onlineOnly !== undefined) query.set('online_only', String(filters.onlineOnly));
    if (filters.unregisteredOnly !== undefined) query.set('unregistered_only', String(filters.unregisteredOnly));
    if (filters.deviceClass) query.set('device_class', filters.deviceClass);
    if (filters.search) query.set('search', filters.search);
    if (filters.archivedOnly !== undefined) query.set('archived_only', String(filters.archivedOnly));
    return this.request('GET', `/api/devices${query.size ? `?${query}` : ''}`);
  }

  getDevice(deviceId: number): Promise<unknown> {
    return this.request('GET', `/api/devices/${deviceId}`);
  }

  listServices(deviceId?: number): Promise<unknown> {
    return this.request('GET', deviceId ? `/api/devices/${deviceId}/services` : '/api/services');
  }

  listPortScans(deviceId: number): Promise<unknown> {
    return this.request('GET', `/api/devices/${deviceId}/ports`);
  }

  topology(): Promise<unknown> {
    return this.request('GET', '/api/inventory/topology');
  }

  segments(): Promise<unknown> {
    return this.request('GET', '/api/segments');
  }

  notifications(unreadOnly: boolean): Promise<unknown> {
    return this.request('GET', `/api/notifications?unread_only=${unreadOnly}`);
  }

  networkChanges(options: {deviceId?: number; sinceHours?: number; search?: string; limit: number}): Promise<unknown> {
    const query = new URLSearchParams({limit: String(options.limit)});
    if (options.deviceId !== undefined) query.set('device_id', String(options.deviceId));
    if (options.sinceHours !== undefined) query.set('since_hours', String(options.sinceHours));
    if (options.search) query.set('search', options.search);
    return this.request('GET', `/api/inventory/changes?${query}`);
  }

  updateDeviceMetadata(deviceId: number, metadata: Record<string, unknown>): Promise<unknown> {
    return this.request('PUT', `/api/devices/${deviceId}`, metadata);
  }
}
