const puppeteer = require('puppeteer-core');
const path = require('path');

const ROUTES = ['/overview', '/actions', '/customers', '/invoices', '/inbox', '/promises', '/forecast', '/reports', '/settings', '/admin/system', '/'];
const BASE_URL = 'http://127.0.0.1:9333';
const SCREENSHOT_DIR = __dirname;

(async () => {
  let browser;
  try {
    const res = await fetch('http://127.0.0.1:9222/json/version');
    const data = await res.json();
    browser = await puppeteer.connect({ browserWSEndpoint: data.webSocketDebuggerUrl });
    console.log('Connected to browser:', data.Browser, '| WS:', data.webSocketDebuggerUrl);
  } catch (e) {
    console.error('Failed to connect to browser:', e.message);
    process.exit(1);
  }

  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080 });

  const screenshots = [];

  for (const route of ROUTES) {
    const slug = route === '/' ? 'home' : route.replace(/\//g, '-').replace(/^-/, '');
    const filePath = path.join(SCREENSHOT_DIR, `shot-${slug}.png`);
    const url = `${BASE_URL}${route}`;

    console.log(`Navigating to ${url} ...`);
    try {
      await page.goto(url, { waitUntil: 'networkidle2', timeout: 30000 });
      await new Promise(r => setTimeout(r, 2000));
      await page.screenshot({ path: filePath, fullPage: true });
      screenshots.push(filePath);
      console.log(`  Saved: ${filePath}`);
    } catch (e) {
      console.error(`  Error on ${route}: ${e.message}`);
    }
  }

  // Low-contrast detection on /overview
  console.log('\nDetecting low-contrast elements on /overview ...');
  try {
    await page.goto(`${BASE_URL}/overview`, { waitUntil: 'networkidle2', timeout: 30000 });
    await new Promise(r => setTimeout(r, 2000));

    const lowContrast = await page.evaluate(() => {
      return Array.from(document.querySelectorAll('*')).filter(el => {
        const s = getComputedStyle(el);
        const bg = s.backgroundColor;
        const c = s.color;
        const bgMatch = bg.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        const cMatch = c.match(/rgba?\((\d+),\s*(\d+),\s*(\d+)/);
        if (!bgMatch || !cMatch) return false;
        const [,br,bg2,bb] = bgMatch.map(Number);
        const [,cr,cg,cb] = cMatch.map(Number);
        return br < 50 && bg2 < 50 && bb < 50 && cr > 80 && cr < 175 && cg > 80 && cg < 175 && cb > 80 && cb < 175 && el.textContent.trim().length > 0;
      }).map(el => ({
        tag: el.tagName,
        cls: el.className?.toString?.()?.slice(0,80),
        text: el.textContent?.trim()?.slice(0,60),
        color: getComputedStyle(el).color,
        bg: getComputedStyle(el).backgroundColor
      }));
    });

    console.log('\n=== LOW-CONTRAST ELEMENTS ===');
    console.log(JSON.stringify(lowContrast, null, 2));
    console.log(`Total: ${lowContrast.length} elements`);
  } catch (e) {
    console.error('Low-contrast detection error:', e.message);
  }

  await page.close();
  console.log('\n=== SCREENSHOTS TAKEN ===');
  screenshots.forEach(s => console.log(s));
})();
