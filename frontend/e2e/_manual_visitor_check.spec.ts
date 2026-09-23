import { test, expect, Page } from '@playwright/test';

const ADMIN_EMAIL = process.env.E2E_ADMIN_EMAIL || 'admin@test.com';
const ADMIN_PASS = process.env.E2E_ADMIN_PASS || 'Admin123!';

async function loginAsAdmin(page: Page) {
    page.on('response', async (res) => {
        if (res.url().includes('/auth/login')) {
            let body = '';
            try { body = (await res.text()).slice(0, 200); } catch { /* ignore */ }
            console.log(`LOGIN RESPONSE ${res.status()} ${res.url()} :: ${body}`);
        }
    });
    await page.goto('/login');
    await page.fill('input[type="email"]', ADMIN_EMAIL);
    await page.fill('input[type="password"]', ADMIN_PASS);
    await page.click('button[type="submit"]');
    await page.waitForURL('/', { timeout: 15000 });
}

test('add-visitor flow: validation + steps', async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/visitors');
    await page.waitForLoadState('networkidle');

    await page.getByRole('button', { name: /add visitor/i }).click();

    await expect(page.getByText(/Step 1 of 2/i)).toBeVisible();
    await expect(page.getByPlaceholder('Subject Name')).toBeVisible();
    await expect(page.getByPlaceholder('Internal Notes', { exact: false })).toBeVisible();

    // 1) Empty name -> blocked
    await page.getByRole('button', { name: /continue enrollment/i }).click();
    await expect(page.getByText(/Subject name is required/i)).toBeVisible();

    // 2) Bad email -> blocked
    await page.getByPlaceholder('Subject Name').fill('E2E Check Person');
    await page.getByPlaceholder('Email Contact').fill('not-an-email');
    await page.getByRole('button', { name: /continue enrollment/i }).click();
    await expect(page.getByText(/valid email address/i)).toBeVisible();

    // 3) Bad phone -> blocked
    await page.getByPlaceholder('Email Contact').fill('good@example.com');
    await page.getByPlaceholder('Phone Line').fill('12');
    await page.getByRole('button', { name: /continue enrollment/i }).click();
    await expect(page.getByText(/valid phone number/i)).toBeVisible();

    // 4) Valid details -> advances to Step 2 (photos)
    await page.getByPlaceholder('Phone Line').fill('+1 555 123 4567');
    await page.getByRole('button', { name: /continue enrollment/i }).click();
    await expect(page.getByText(/Step 2 of 2/i)).toBeVisible();
    await expect(page.getByText(/Face image required/i)).toBeVisible();

    console.log('PASS: validation gates name, email, phone; advances to photo step.');
});
