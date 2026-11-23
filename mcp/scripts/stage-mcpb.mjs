import {cp, mkdir, readFile, rm, writeFile} from 'node:fs/promises';
import {resolve} from 'node:path';

const root = resolve(import.meta.dirname, '..');
const target = resolve(root, 'build/mcpb');
await rm(target, {recursive: true, force: true});
await mkdir(resolve(target, 'server'), {recursive: true});
await cp(resolve(root, 'dist/bundle.js'), resolve(target, 'server/index.js'));
await cp(resolve(root, 'mcpb/manifest.json'), resolve(target, 'manifest.json'));
await cp(resolve(root, 'mcpb/logo.png'), resolve(target, 'logo.png'));

const bundle = await readFile(resolve(target, 'server/index.js'), 'utf8');
await writeFile(resolve(target, 'server/index.js'), bundle.replace(/^#!.*\n#!.*\n/, '#!/usr/bin/env node\n'));
