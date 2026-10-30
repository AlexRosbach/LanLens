import { createServer } from 'node:http';
import { timingSafeEqual } from 'node:crypto';

import { createMcpHandler } from '@modelcontextprotocol/server';
import { hostHeaderValidation, originValidation, toNodeHandler } from '@modelcontextprotocol/node';

import type { LanLensMcpConfig } from './config.js';
import { createLanLensMcpServer } from './server.js';

function secureEqual(actual: string | undefined, expected: string): boolean {
  if (!actual) return false;
  const left = Buffer.from(actual);
  const right = Buffer.from(expected);
  return left.length === right.length && timingSafeEqual(left, right);
}

export async function serveHttp(config: LanLensMcpConfig): Promise<void> {
  const handler = createMcpHandler(() => createLanLensMcpServer(config), {
    legacy: 'stateless',
    maxRequestBodySize: 1024 * 1024,
    onerror: (error) => console.error(`[lanlens-mcp] ${error.message}`),
  });
  const nodeHandler = toNodeHandler(handler, {
    maxRequestBodySize: 1024 * 1024,
    onerror: (error) => console.error(`[lanlens-mcp] ${error.message}`),
  });
  const validateHost = hostHeaderValidation(config.allowedHosts);
  const validateOrigin = originValidation(config.allowedHosts.map((host) => host.replace(/^\[|\]$/g, '')));

  const httpServer = createServer((request, response) => {
    const path = new URL(request.url ?? '/', `http://${request.headers.host ?? 'localhost'}`).pathname;
    if (path === '/health' && request.method === 'GET') {
      response.writeHead(200, {'content-type': 'application/json'});
      response.end(JSON.stringify({
        status: 'ok',
        service: 'LanLens MCP',
        version: process.env.LANLENS_MCP_VERSION ?? '1.6.1',
        build_code: process.env.LANLENS_MCP_BUILD_CODE ?? 'dev',
        build_commit: process.env.LANLENS_MCP_BUILD_COMMIT ?? 'unknown',
        build_branch: process.env.LANLENS_MCP_BUILD_BRANCH ?? 'unknown',
        build_created: process.env.LANLENS_MCP_BUILD_CREATED ?? 'unknown',
      }));
      return;
    }
    if (path !== '/mcp') {
      response.writeHead(404, {'content-type': 'application/json'});
      response.end(JSON.stringify({error: 'Not found'}));
      return;
    }
    if (!validateHost(request, response) || !validateOrigin(request, response)) return;
    if (config.httpToken) {
      const authorization = request.headers.authorization;
      if (!authorization?.startsWith('Bearer ') || !secureEqual(authorization.slice(7), config.httpToken)) {
        response.writeHead(401, {
          'content-type': 'application/json',
          'www-authenticate': 'Bearer realm="lanlens-mcp"',
        });
        response.end(JSON.stringify({error: 'Unauthorized'}));
        return;
      }
    }
    void nodeHandler(request, response);
  });

  await new Promise<void>((resolve, reject) => {
    httpServer.once('error', reject);
    httpServer.listen(config.port, config.host, () => resolve());
  });
  console.error(`[lanlens-mcp] Streamable HTTP listening on http://${config.host}:${config.port}/mcp`);

  const shutdown = async () => {
    await handler.close();
    httpServer.close(() => process.exit(0));
  };
  process.once('SIGINT', () => void shutdown());
  process.once('SIGTERM', () => void shutdown());
}
