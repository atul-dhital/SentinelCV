const fs = require('fs');
const path = require('path');
// Script lives in scripts/docs-tooling/; repo root is two levels up.
const repoRoot = path.join(__dirname, '..', '..');
const { chromium } = require(path.join(repoRoot, 'frontend', 'node_modules', '@playwright', 'test'));

const outDir = path.join(repoRoot, 'page_screenshots');
if (!fs.existsSync(outDir)) fs.mkdirSync(outDir, { recursive: true });

const baseURL = 'http://localhost:3001';
const pages = [
  { url: '/login', name: '01-login' },
  { url: '/', name: '02-home' },
  { url: '/visitors', name: '03-visitors' },
  { url: '/logs', name: '04-logs' },
  { url: '/reports', name: '05-reports' },
  { url: '/settings', name: '06-settings' },
  { url: '/live-activities', name: '07-live-activities' },
  { url: '/edge-devices', name: '08-edge-devices' },
  { url: '/liveness', name: '09-liveness' },
];

async function login(page) {
  await page.goto(`${baseURL}/login`, { waitUntil: 'domcontentloaded' });
  await page.locator('input[type="email"]').first().fill('admin@test.com');
  await page.locator('input[type="password"]').first().fill('Admin123!');
  await page.click('button[type="submit"]');
  await page.waitForURL('**/');
  await page.waitForTimeout(1500);
}

async function capture(page, url, name) {
  await page.goto(`${baseURL}${url}`, { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(2500);
  await page.screenshot({ path: path.join(outDir, `${name}.png`), fullPage: true });
  console.log(`saved ${name}`);
}

(async () => {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1800 }, deviceScaleFactor: 1 });
  try {
    await login(page);
  } catch (err) {
    console.error('login failed, continuing with public pages only:', err.message);
  }

  for (const p of pages) {
    try {
      await capture(page, p.url, p.name);
    } catch (err) {
      console.error(`failed ${p.url}:`, err.message);
    }
  }

  await browser.close();
})();
