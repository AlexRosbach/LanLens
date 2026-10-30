import assert from 'node:assert/strict';
import test from 'node:test';

import {sanitizeDevice, sanitizeTopology} from '../src/sanitize.js';
import {deviceFixture} from './helpers.js';

test('device output omits secret and operator-private fields', () => {
  const sanitized = sanitizeDevice(deviceFixture);
  assert.equal(sanitized.id, 1);
  assert.equal('password_location' in sanitized, false);
  assert.equal('notes' in sanitized, false);
  assert.equal('manual_connect_entries' in sanitized, false);
  assert.deepEqual((sanitized.latest_scan as {open_ports: unknown[]}).open_ports, [
    {port: 22, protocol: 'tcp', service: 'ssh'},
  ]);
});

test('topology output omits raw discovery metadata', () => {
  const sanitized = sanitizeTopology({
    nodes: [{id: 1, label: 'server', metadata: {secret: true}}],
    edges: [{source: 1, target: 2, relationship_type: 'snmp', metadata: {community: 'private'}}],
  });
  assert.equal('metadata' in (sanitized.nodes as Record<string, unknown>[])[0]!, false);
  assert.equal('metadata' in (sanitized.edges as Record<string, unknown>[])[0]!, false);
});
