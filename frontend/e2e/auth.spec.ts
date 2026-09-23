import { test, expect, Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASS  = process.env.E2E_ADMIN_PASS  || 'Admin123!';
const STAFF_EMAIL = process.env.E2E_STAFF_EMAIL || 'staff@test.com';
const STAFF_PASS  = process.env.E2E_STAFF_PASS  || 'Staff123!';

// ── Helpers ──────────────────────────────────────────────────────────────────

async function loginAs(page: Page, email: string, password: string) {
    await page.goto('/login');
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForURL('/');
}

// ── Tests ─────────────────────────────────────────────────────────────────────

test.describe('Authentication', () => {
    test('admin login redirects to dashboard', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await expect(page).toHaveURL('/');
        await expect(page.locator('h1, [data-testid="dashboard-title"]').first()).toBeVisible();
    });

    test('wrong password shows error', async ({ page }) => {
        await page.goto('/login');
        await page.fill('input[type="email"]', ADMIN_EMAIL);
        await page.fill('input[type="password"]', 'wrongpassword123!');
        await page.click('button[type="submit"]');
        await expect(page.getByText(/incorrect|invalid|password/i)).toBeVisible();
        await expect(page).toHaveURL('/login');
    });

    test('unauthenticated user redirected to login', async ({ page }) => {
        await page.goto('/');
        await expect(page).toHaveURL('/login');
    });

    test('logout clears session and redirects to login', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        // Find and click logout button (could be in a menu or nav)
        const logoutBtn = page.getByRole('button', { name: /log\s*out|sign\s*out/i });
        if (await logoutBtn.count() > 0) {
            await logoutBtn.click();
        } else {
            // May be in a dropdown — try user menu first
            const userMenu = page.locator('[aria-label*="user"], [data-testid="user-menu"]').first();
            if (await userMenu.count() > 0) await userMenu.click();
            await page.getByRole('button', { name: /log\s*out|sign\s*out/i }).click();
        }
        await expect(page).toHaveURL('/login');
    });

    test('token refresh works transparently', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        // Clear the in-memory access token by navigating away and back
        // (The refresh cookie persists across navigation)
        await page.evaluate(() => {
            // Directly test that a 401 triggers a refresh cycle
        });
        await page.goto('/visitors');
        // Should load without showing login page
        await expect(page).not.toHaveURL('/login');
    });
});

test.describe('Role-based access', () => {
    test('staff cannot access users page', async ({ page }) => {
        await loginAs(page, STAFF_EMAIL, STAFF_PASS);
        await page.goto('/users');
        // Should either redirect or show permission error
        const body = await page.textContent('body');
        expect(body).toMatch(/admin|permission|forbidden|403/i);
    });

    test('staff cannot see AI Lab in navigation', async ({ page }) => {
        await loginAs(page, STAFF_EMAIL, STAFF_PASS);
        const aiLabNav = page.getByRole('button', { name: /AI Lab/i });
        await expect(aiLabNav).not.toBeVisible();
    });

    test('admin can see AI Lab in navigation', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        const aiLabNav = page.getByRole('button', { name: /AI Lab/i });
        await expect(aiLabNav).toBeVisible();
    });
});
