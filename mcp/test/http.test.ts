import assert from 'node:assert/strict';
import {spawn, type ChildProcess} from 'node:child_process';
import {createServer} from 'node:http';
import test from 'node:test';

import {Client, StreamableHTTPClientTransport} from '@modelcontextprotocol/client';

import {startMockLanLens} from './helpers.js';

async function availablePort(): Promise<number> {
  const server = createServer();
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string') throw new Error('Could not allocate a test port');
  const port = address.port;
  await new Promise<void>((resolve, reject) => server.close((error) => error ? reject(error) : resolve()));
  return port;
}

async function waitForHealth(url: string, child: ChildProcess): Promise<void> {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (child.exitCode !== null) throw new Error(`MCP process exited with ${child.exitCode}`);
    try {
      const response = await fetch(url);
      if (response.ok) return;
    } catch {
      // Startup race.
    }
    await new Promise((resolve) => setTimeout(resolve, 50));
  }
  throw new Error('MCP HTTP server did not start');
}

test('serves authenticated Streamable HTTP and rejects unauthenticated calls', async () => {
  const mock = await startMockLanLens();
  const port = await availablePort();
  const httpToken = 'm'.repeat(40);
  let stderr = '';
  const child = spawn(process.execPath, ['dist/index.js', '--transport=http'], {
    cwd: process.cwd(),
    env: {
      ...process.env,
      LANLENS_URL: mock.url,
      LANLENS_API_TOKEN: 't'.repeat(40),
      LANLENS_MCP_HOST: '127.0.0.1',
      LANLENS_MCP_PORT: String(port),
      LANLENS_MCP_HTTP_TOKEN: httpToken,
    },
    stdio: ['ignore', 'ignore', 'pipe'],
  });
  child.stderr?.on('data', (chunk) => { stderr += String(chunk); });

  try {
    await waitForHealth(`http://127.0.0.1:${port}/health`, child);
    const unauthorized = await fetch(`http://127.0.0.1:${port}/mcp`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({jsonrpc: '2.0', id: 1, method: 'initialize', params: {}}),
    });
    assert.equal(unauthorized.status, 401);

    const client = new Client({name: 'http-test', version: '1.0.0'});
    const transport = new StreamableHTTPClientTransport(new URL(`http://127.0.0.1:${port}/mcp`), {
      authProvider: {token: async () => httpToken},
    });
    await client.connect(transport);
    const health = await client.callTool({name: 'get_health', arguments: {}});
    assert.equal(health.isError, undefined);
    await client.close();
  } finally {
    child.kill('SIGTERM');
    await new Promise<void>((resolve) => child.once('exit', () => resolve()));
    await mock.close();
  }
  assert.match(stderr, /Streamable HTTP listening/);
});
