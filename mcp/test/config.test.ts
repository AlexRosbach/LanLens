import assert from 'node:assert/strict';
import test from 'node:test';

import {loadConfig} from '../src/config.js';

const token = 'a'.repeat(40);

test('defaults to safe local stdio configuration', () => {
  const config = loadConfig([], {LANLENS_API_TOKEN: token});
  assert.equal(config.transport, 'stdio');
  assert.equal(config.enableWrites, false);
  assert.equal(config.lanlensUrl, 'http://127.0.0.1:7765');
});

test('rejects a short LanLens token', () => {
  assert.throws(() => loadConfig([], {LANLENS_API_TOKEN: 'short'}), /minimum 32 characters/);
});

test('requires an MCP token and host allowlist for external HTTP binds', () => {
  assert.throws(() => loadConfig([], {
    LANLENS_API_TOKEN: token,
    LANLENS_MCP_TRANSPORT: 'http',
    LANLENS_MCP_HOST: '0.0.0.0',
  }), /HTTP_TOKEN/);
  assert.throws(() => loadConfig([], {
    LANLENS_API_TOKEN: token,
    LANLENS_MCP_TRANSPORT: 'http',
    LANLENS_MCP_HOST: '0.0.0.0',
    LANLENS_MCP_HTTP_TOKEN: 'b'.repeat(40),
  }), /ALLOWED_HOSTS/);
});

test('accepts an explicitly protected external HTTP bind', () => {
  const config = loadConfig([], {
    LANLENS_API_TOKEN: token,
    LANLENS_MCP_TRANSPORT: 'http',
    LANLENS_MCP_HOST: '0.0.0.0',
    LANLENS_MCP_HTTP_TOKEN: 'b'.repeat(40),
    LANLENS_MCP_ALLOWED_HOSTS: 'mcp.example.test,localhost',
  });
  assert.equal(config.host, '0.0.0.0');
  assert.deepEqual(config.allowedHosts, ['mcp.example.test', 'localhost']);
});
