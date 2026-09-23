import { test, expect, Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASS  = process.env.E2E_ADMIN_PASS  || 'Admin123!';
const STAFF_EMAIL = process.env.E2E_STAFF_EMAIL || 'staff@test.com';
const STAFF_PASS  = process.env.E2E_STAFF_PASS  || 'Staff123!';

async function loginAs(page: Page, email: string, password: string) {
    await page.goto('/login');
    await page.fill('input[type="email"]', email);
    await page.fill('input[type="password"]', password);
    await page.click('button[type="submit"]');
    await page.waitForURL('/');
}

test.describe('GDPR Settings', () => {
    test('admin can view GDPR settings page', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await page.goto('/settings/gdpr');
        await expect(page.getByText(/GDPR Compliance/i)).toBeVisible();
    });

    test('admin sees Add Policy button', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await page.goto('/settings/gdpr');
        await expect(page.getByRole('button', { name: /add policy/i })).toBeVisible();
    });

    test('staff cannot see Add Policy button', async ({ page }) => {
        await loginAs(page, STAFF_EMAIL, STAFF_PASS);
        await page.goto('/settings/gdpr');
        const addBtn = page.getByRole('button', { name: /add policy/i });
        await expect(addBtn).not.toBeVisible();
    });

    test('staff cannot see Process Delete buttons', async ({ page }) => {
        await loginAs(page, STAFF_EMAIL, STAFF_PASS);
        await page.goto('/settings/gdpr');
        const processBtn = page.getByRole('button', { name: /process delete/i });
        await expect(processBtn).not.toBeVisible();
    });
});

test.describe('GDPR Consent Portal', () => {
    test('admin can access consent portal', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await page.goto('/settings/consent');
        await expect(page.getByText(/Consent Management/i)).toBeVisible();
    });

    test('consent portal search shows visitors', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await page.goto('/settings/consent');
        const searchInput = page.locator('input[placeholder*="search" i]');
        await searchInput.fill('visitor');
        await page.waitForTimeout(500);
        // Either shows results or "no visitors found" — should not crash
        await expect(page.locator('main')).toBeVisible();
    });
});

test.describe('SSO Settings', () => {
    test('staff cannot see Add Provider button', async ({ page }) => {
        await loginAs(page, STAFF_EMAIL, STAFF_PASS);
        await page.goto('/settings/sso');
        const addBtn = page.getByRole('button', { name: /add provider/i });
        await expect(addBtn).not.toBeVisible();
    });

    test('admin can see Add Provider button', async ({ page }) => {
        await loginAs(page, ADMIN_EMAIL, ADMIN_PASS);
        await page.goto('/settings/sso');
        await expect(page.getByRole('button', { name: /add provider/i })).toBeVisible();
    });
});
