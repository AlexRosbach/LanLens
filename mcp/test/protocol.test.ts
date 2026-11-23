import assert from 'node:assert/strict';
import test from 'node:test';

import {Client, InMemoryTransport} from '@modelcontextprotocol/client';

import type {LanLensMcpConfig} from '../src/config.js';
import {createLanLensMcpServer} from '../src/server.js';
import {startMockLanLens, type MockLanLens} from './helpers.js';

const apiToken = 't'.repeat(40);

function config(mock: MockLanLens, enableWrites = false): LanLensMcpConfig {
  return {
    lanlensUrl: mock.url,
    apiToken,
    enableWrites,
    requestTimeoutMs: 5_000,
    transport: 'stdio',
    host: '127.0.0.1',
    port: 8787,
    allowedHosts: ['localhost'],
  };
}

async function connectedClient(mock: MockLanLens, enableWrites = false) {
  const server = createLanLensMcpServer(config(mock, enableWrites));
  const client = new Client({name: 'lanlens-test', version: '1.0.0'});
  const [clientTransport, serverTransport] = InMemoryTransport.createLinkedPair();
  await server.connect(serverTransport);
  await client.connect(clientTransport);
  return {client, server};
}

test('lists the stable LanLens tools and resources', async () => {
  const mock = await startMockLanLens();
  const {client, server} = await connectedClient(mock);
  try {
    const tools = await client.listTools();
    assert.deepEqual(tools.tools.map((tool) => tool.name).sort(), [
      'get_device', 'get_health', 'get_topology', 'list_devices', 'list_network_changes',
      'list_notifications', 'list_open_ports', 'list_segments', 'list_services',
    ]);
    const resources = await client.listResources();
    assert.equal(resources.resources.some((resource) => resource.uri === 'lanlens://health'), true);
    const templates = await client.listResourceTemplates();
    assert.equal(templates.resourceTemplates.some((template) => template.uriTemplate === 'lanlens://devices/{deviceId}'), true);
  } finally {
    await client.close();
    await server.close();
    await mock.close();
  }
});

test('returns sanitized device data and authenticates with the LanLens token', async () => {
  const mock = await startMockLanLens();
  const {client, server} = await connectedClient(mock);
  try {
    const result = await client.callTool({name: 'get_device', arguments: {device_id: 1}});
    assert.equal(result.isError, undefined);
    const output = (result.structuredContent as {result: Record<string, unknown>}).result;
    assert.equal(output.hostname, 'server');
    assert.equal('password_location' in output, false);
    assert.equal(mock.requests[0]?.authorization, `Bearer ${apiToken}`);
  } finally {
    await client.close();
    await server.close();
    await mock.close();
  }
});

test('does not advertise write tools unless explicitly enabled', async () => {
  const mock = await startMockLanLens();
  const {client, server} = await connectedClient(mock);
  try {
    const tools = await client.listTools();
    assert.equal(tools.tools.some((tool) => tool.name === 'update_device_metadata'), false);
    assert.equal(mock.requests.some((request) => request.method === 'PUT'), false);
  } finally {
    await client.close();
    await server.close();
    await mock.close();
  }
});

test('allows only the safe metadata mutation when both write gates permit it', async () => {
  const mock = await startMockLanLens();
  const {client, server} = await connectedClient(mock, true);
  try {
    const tools = await client.listTools();
    assert.equal(tools.tools.some((tool) => tool.name === 'update_device_metadata'), true);
    const result = await client.callTool({
      name: 'update_device_metadata',
      arguments: {device_id: 1, location: 'Rack B', responsible: 'Ops'},
    });
    assert.equal(result.isError, undefined);
    const write = mock.requests.find((request) => request.method === 'PUT');
    assert.deepEqual(write?.body, {location: 'Rack B', responsible: 'Ops'});
  } finally {
    await client.close();
    await server.close();
    await mock.close();
  }
});
