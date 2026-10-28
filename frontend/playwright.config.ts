import { defineConfig } from '@playwright/test';
import { existsSync, mkdirSync, realpathSync } from 'node:fs';
import { randomUUID } from 'node:crypto';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const localRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../.local');
if (process.argv.some(arg => arg === '--output' || arg.startsWith('--output=') || arg.startsWith('-o'))) {
  throw new Error('Use E2E_OUTPUT_DIR as an evidence parent; CLI --output may delete old evidence.');
}
mkdirSync(localRoot, { recursive: true });
const requested = process.env.E2E_OUTPUT_DIR ? path.resolve(process.env.E2E_OUTPUT_DIR) : path.join(localRoot, 'browser-runs');
if (!requested.startsWith(localRoot + path.sep)) throw new Error('E2E_OUTPUT_DIR must be inside project .local');
const realRoot = realpathSync(localRoot);
let ancestor = requested;
while (!existsSync(ancestor)) ancestor = path.dirname(ancestor);
const realAncestor = realpathSync(ancestor);
if (realAncestor !== realRoot && !realAncestor.startsWith(realRoot + path.sep)) throw new Error('Evidence parent escapes .local');
mkdirSync(requested, { recursive: true });
const realRequested = realpathSync(requested);
if (!realRequested.startsWith(realRoot + path.sep)) throw new Error('Evidence directory must stay inside .local');
const outputDir = path.join(realRequested, `run-${Date.now()}-${randomUUID()}`);
mkdirSync(outputDir); // Exclusive creation; never pass an existing run directory to Playwright.

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  outputDir,
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    headless: true,
    trace: 'off',
    screenshot: 'off',
  },
});
