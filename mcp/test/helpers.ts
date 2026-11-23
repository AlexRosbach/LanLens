import {createServer, type IncomingMessage, type ServerResponse} from 'node:http';
import type {AddressInfo} from 'node:net';

export interface MockLanLens {
  url: string;
  requests: Array<{method: string; path: string; authorization?: string; body?: unknown}>;
  close(): Promise<void>;
}

async function readJson(request: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) chunks.push(Buffer.from(chunk));
  if (!chunks.length) return undefined;
  return JSON.parse(Buffer.concat(chunks).toString('utf8'));
}

function send(response: ServerResponse, status: number, value: unknown): void {
  response.writeHead(status, {'content-type': 'application/json'});
  response.end(JSON.stringify(value));
}

export async function startMockLanLens(): Promise<MockLanLens> {
  const requests: MockLanLens['requests'] = [];
  const server = createServer(async (request, response) => {
    const body = await readJson(request);
    const path = request.url ?? '/';
    requests.push({
      method: request.method ?? 'GET',
      path,
      authorization: request.headers.authorization,
      body,
    });
    if (request.headers.authorization !== `Bearer ${'t'.repeat(40)}`) {
      send(response, 401, {detail: 'Not authenticated'});
      return;
    }
    if (path === '/api/health') {
      send(response, 200, {status: 'ok', version: '1.6.1', build_code: 'test'});
      return;
    }
    if (path.startsWith('/api/devices?') || path === '/api/devices') {
      send(response, 200, {
        items: [deviceFixture], total: 1, online: 1, offline: 0, unregistered: 0, archived: 0,
      });
      return;
    }
    if (path === '/api/devices/1' && request.method === 'GET') {
      send(response, 200, deviceFixture);
      return;
    }
    if (path === '/api/devices/1' && request.method === 'PUT') {
      send(response, 200, {...deviceFixture, ...(body as object)});
      return;
    }
    if (path === '/api/devices/1/services' || path === '/api/services') {
      send(response, 200, [{id: 4, device_id: 1, name: 'SSH', port: 22, protocol: 'ssh'}]);
      return;
    }
    if (path === '/api/devices/1/ports') {
      send(response, 200, [deviceFixture.latest_scan]);
      return;
    }
    if (path === '/api/inventory/topology') {
      send(response, 200, {nodes: [{id: 1, label: 'server', metadata: {secret: true}}], edges: []});
      return;
    }
    if (path === '/api/segments') {
      send(response, 200, [{id: 1, name: 'LAN', color: '#fff', ip_start: '192.0.2.1', ip_end: '192.0.2.254'}]);
      return;
    }
    if (path.startsWith('/api/notifications')) {
      send(response, 200, [{id: 1, event_type: 'device_online', message: 'Online', is_read: false}]);
      return;
    }
    if (path.startsWith('/api/inventory/changes')) {
      send(response, 200, [{id: 1, device_id: 1, event_type: 'device_updated', field: 'location'}]);
      return;
    }
    send(response, 404, {detail: 'Not found'});
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address() as AddressInfo;
  return {
    url: `http://127.0.0.1:${address.port}`,
    requests,
    close: () => new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve())),
  };
}

export const deviceFixture = {
  id: 1,
  mac_address: '00:11:22:33:44:55',
  ip_address: '192.0.2.10',
  hostname: 'server',
  display_name: 'Server',
  device_class: 'Linux Server',
  vendor: 'Example',
  location: 'Rack A',
  is_registered: true,
  is_online: true,
  first_seen: '2026-10-30T10:00:00Z',
  last_seen: '2026-10-30T10:10:00Z',
  password_location: 'vault/secret/path',
  notes: 'private operator note',
  manual_connect_entries: [{url: 'ssh://secret-host'}],
  services: [{id: 4, device_id: 1, name: 'SSH', port: 22, protocol: 'ssh'}],
  latest_scan: {
    id: 3,
    scanned_at: '2026-10-30T10:05:00Z',
    open_ports: [{port: 22, protocol: 'tcp', service: 'ssh', banner: 'sensitive banner'}],
    ssh_available: true,
    rdp_available: false,
    http_available: false,
    https_available: false,
  },
};
