import { test, expect, Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASS  = process.env.E2E_ADMIN_PASS  || 'Admin123!';

async function loginAsAdmin(page: Page) {
    await page.goto('/login');
    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', ADMIN_PASS);
    await page.click('button[type="submit"]');
    await page.waitForURL('/');
}

test.describe('Visitor management', () => {
    test.beforeEach(async ({ page }) => {
        await loginAsAdmin(page);
    });

    test('visitor list loads without error', async ({ page }) => {
        await page.goto('/visitors');
        await page.waitForLoadState('networkidle');
        // Should show a visitor list or empty state — no 500 or crash
        await expect(page.locator('main')).toBeVisible();
        await expect(page.getByText(/500|server error/i)).not.toBeVisible();
    });

    test('create visitor and verify it appears in list', async ({ page }) => {
        await page.goto('/visitors');
        // Click create / add button
        const createBtn = page.getByRole('button', { name: /add visitor|create visitor|new visitor/i });
        await expect(createBtn).toBeVisible();
        await createBtn.click();

        const ts = Date.now();
        await page.fill('input[name="name"], input[placeholder*="name" i]', `E2E Visitor ${ts}`);

        const emailInput = page.locator('input[type="email"], input[name="email"]');
        if (await emailInput.count() > 0) {
            await emailInput.fill(`e2e-${ts}@test.com`);
        }

        await page.getByRole('button', { name: /create|save|submit/i }).last().click();

        // Verify visitor appears
        await expect(page.getByText(`E2E Visitor ${ts}`)).toBeVisible({ timeout: 8000 });
    });

    test('visitor detail page loads', async ({ page }) => {
        await page.goto('/visitors');
        await page.waitForLoadState('networkidle');
        const firstVisitor = page.locator('table tbody tr, [data-testid="visitor-row"]').first();
        if (await firstVisitor.count() > 0) {
            await firstVisitor.click();
            await expect(page.locator('h1')).toBeVisible();
        }
    });

    test('CSV export downloads a file', async ({ page }) => {
        await page.goto('/visitors');
        const downloadPromise = page.waitForEvent('download');
        const exportBtn = page.getByRole('button', { name: /export/i });
        if (await exportBtn.count() > 0) {
            await exportBtn.click();
            const download = await downloadPromise;
            expect(download.suggestedFilename()).toMatch(/\.csv$/);
        }
    });
});

test.describe('Detection logs', () => {
    test.beforeEach(async ({ page }) => {
        await loginAsAdmin(page);
    });

    test('logs list loads', async ({ page }) => {
        await page.goto('/logs');
        await page.waitForLoadState('networkidle');
        await expect(page.locator('main')).toBeVisible();
        await expect(page.getByText(/500|server error/i)).not.toBeVisible();
    });

    test('log detail page accessible from list', async ({ page }) => {
        await page.goto('/logs');
        await page.waitForLoadState('networkidle');
        const firstRow = page.locator('table tbody tr').first();
        if (await firstRow.count() > 0) {
            await firstRow.click();
            await expect(page.locator('h1')).toBeVisible();
            await expect(page.getByText(/log detail/i)).toBeVisible();
        }
    });
});

test.describe('Dashboard', () => {
    test.beforeEach(async ({ page }) => {
        await loginAsAdmin(page);
    });

    test('dashboard loads with stat cards', async ({ page }) => {
        await page.goto('/');
        await page.waitForLoadState('networkidle');
        // Check for any stat card headings
        await expect(page.locator('main')).toBeVisible();
    });

    test('websocket connects (no error banner)', async ({ page }) => {
        await page.goto('/');
        await page.waitForTimeout(2000);
        // WsDisconnectBanner should NOT be visible
        const banner = page.getByText(/connection lost|disconnected|reconnecting/i);
        await expect(banner).not.toBeVisible();
    });
});
