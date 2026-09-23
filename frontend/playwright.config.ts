import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright E2E test configuration for SentinelCV dashboard.
 *
 * Quick-start (all-in-one):
 *   cd frontend && npm run e2e:local        # starts backend + frontend, runs tests
 *
 * Against running stack:
 *   E2E_BASE_URL=http://localhost:3001 npm run e2e
 *
 * CI:
 *   The ci.yml e2e-tests job starts the stack via Docker Compose before running.
 *
 * Debug / interactive:
 *   npm run e2e:ui
 *   npx playwright test --debug
 */

const BASE_URL = process.env.E2E_BASE_URL || 'http://localhost:3001';
const BACKEND_URL = process.env.E2E_BACKEND_URL || 'http://localhost:8000';

// When E2E_EXTERNAL=1, assume services are already running (CI / staging).
// Otherwise Playwright starts the Next.js dev server automatically.
const useExternalServer = process.env.E2E_EXTERNAL === '1' || !!process.env.E2E_BASE_URL;

export default defineConfig({
    testDir: './e2e',
    fullyParallel: false,       // sequential — tests share a backend DB state
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    workers: 1,
    reporter: [
        ['list'],
        ['html', { open: 'never', outputFolder: 'playwright-report' }],
        ...(process.env.CI ? [['github'] as [string]] : []),
    ],
    use: {
        baseURL: BASE_URL,
        trace: 'on-first-retry',
        screenshot: 'only-on-failure',
        video: 'retain-on-failure',
        // Pass backend URL to tests via storageState / env
        extraHTTPHeaders: { 'x-e2e-backend-url': BACKEND_URL },
    },
    // Automatically start Next.js dev server when running locally
    ...(useExternalServer ? {} : {
        webServer: {
            // `env` below already passes NEXT_PUBLIC_API_URL through cross-platform —
            // do not prefix the command with `VAR=value` (Unix-only syntax, breaks on
            // Windows cmd.exe with "not recognized as an internal or external command").
            command: 'npm run dev',
            url: BASE_URL,
            reuseExistingServer: true,
            timeout: 60_000,
            env: {
                NEXT_PUBLIC_API_URL: `${BACKEND_URL}/api/v1`,
            },
        },
    }),
    projects: [
        {
            name: 'chromium',
            use: { ...devices['Desktop Chrome'] },
        },
    ],
});
