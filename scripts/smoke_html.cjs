const { chromium } = require('playwright');
const { writeFile } = require('node:fs/promises');

(async () => {
  const base = 'http://127.0.0.1:8765/outputs/phase4-fixture';
  const results = [];
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.ERA_CHROME_PATH || 'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe'
  });
  for (const filename of ['enterprise_dashboard.html', 'product_dashboard.html']) {
    for (const width of [360, 768, 1440]) {
      const page = await browser.newPage({viewport: {width, height: 900}});
      const errors = [];
      page.on('console', message => { if (message.type() === 'error') errors.push(message.text()); });
      page.on('pageerror', error => errors.push(String(error)));
      await page.goto(`${base}/${filename}`, {waitUntil: 'networkidle'});
      await page.screenshot({path: `outputs/phase4-fixture/${filename.replace('.html', '')}-${width}.png`, fullPage: true});
      const bodyWidth = await page.evaluate(() => document.body.scrollWidth);
      const record = {file: filename, width, overflow: bodyWidth > width + 2, errors};
      if (filename.startsWith('product')) {
        record.cards = await page.locator('.product-card').count();
        await page.locator('[data-compare]').first().click();
        record.compareTable = await page.locator('#comparePanel table').count();
        await page.locator('[data-detail]').first().click();
        record.dialogOpen = await page.locator('#productDialog').evaluate(element => element.open);
      }
      results.push(record);
      await page.close();
    }
  }
  await browser.close();
  await writeFile('outputs/phase4-fixture/html-smoke-results.json', JSON.stringify(results, null, 2), 'utf8');
  console.log(JSON.stringify(results, null, 2));
})().catch(error => { console.error(error); process.exit(1); });
