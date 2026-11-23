#!/usr/bin/env node
import { serveStdio } from '@modelcontextprotocol/server/stdio';

import { loadConfig } from './config.js';
import { serveHttp } from './http.js';
import { createLanLensMcpServer } from './server.js';

async function main(): Promise<void> {
  const config = loadConfig();
  if (config.transport === 'http') {
    await serveHttp(config);
    return;
  }
  serveStdio(() => createLanLensMcpServer(config), {
    onerror: (error) => console.error(`[lanlens-mcp] ${error.message}`),
  });
}

main().catch((error: unknown) => {
  const message = error instanceof Error ? error.message : 'Unknown startup failure';
  console.error(`[lanlens-mcp] ${message}`);
  process.exitCode = 1;
});
