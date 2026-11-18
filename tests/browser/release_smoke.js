// Release smoke test for a deployed Quant Lab (no writes; safe against production).
//   node tests/browser/release_smoke.js <base-url> <output.json> [screenshot-folder]
// Walks the release journeys and records what the page shows; release_check.py compares
// the numbers with the library.
const { chromium } = require('playwright');
const fs = require('fs');
const path = require('path');
const [base, outFile, shots] = [process.argv[2].replace(/\/$/, ''), process.argv[3], process.argv[4]];
const out = { url: base, checks: [], shown: {} };
const check = (id, pass, note = '') => { out.checks.push({ id, pass: !!pass, note }); console.log(`${pass ? 'PASS' : 'FAIL'} ${id} ${note}`); };
const idle = async p => {
  await p.waitForTimeout(1000);
  await p.waitForFunction(() => !document.querySelector('[data-testid="stStatusWidget"]'), null, { timeout: 180000 }).catch(() => {});
  await p.waitForTimeout(1000);
};
const broken = p => p.locator('[data-testid="stException"]').count();
const metric = async (p, label) => (await p.locator('[data-testid="stMetric"]', { hasText: label }).first()
  .locator('[data-testid="stMetricValue"]').innerText()).trim();
const delta = async (p, label) => (await p.locator('[data-testid="stMetric"]', { hasText: label }).first()
  .locator('[data-testid="stMetricDelta"]').innerText().catch(() => '')).trim();

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on('pageerror', e => errors.push(String(e).slice(0, 200)));
  try {
    // R1 open the application
    const response = await page.goto(base + '/', { timeout: 180000 });
    await page.waitForSelector('[data-testid="stMain"] h1', { timeout: 240000 }); await idle(page);
    check('R1 application opens', response && response.status() < 400 && !(await broken(page)), `HTTP ${response && response.status()}`);
    // R2 Investment Lab through the sidebar
    await page.locator('[data-testid="stSidebarNav"] a', { hasText: 'Investment Lab' }).first().click(); await idle(page);
    await page.waitForSelector('[data-testid="stMetric"]', { timeout: 180000 }); await idle(page);
    check('R2 Investment Lab opens', (await page.locator('[data-testid="stMain"] h1').innerText()).includes('Investment Lab') && !(await broken(page)));
    // R3 Future Wealth mode
    await page.getByRole('radio', { name: 'Future wealth' }).click(); await idle(page);
    await page.waitForSelector('text=FUTURE WEALTH', { timeout: 180000 }); await idle(page);
    check('R3 Future Wealth mode opens', !(await broken(page)));
    // R4 a projection is generated; read the headline numbers
    for (const label of ['Median after 10 yr', 'Reach $100k by year 10', 'Hold it at the end', 'End below what you paid in', 'Total you pay in'])
      out.shown[label] = { value: await metric(page, label).catch(() => null), delta: await delta(page, label) };
    check('R4 projection generated', Object.values(out.shown).every(v => v.value), JSON.stringify(Object.fromEntries(Object.entries(out.shown).map(([k, v]) => [k, v.value]))));
    const badge = await page.locator('.ql-badge', { hasText: 'MODEL:' }).first().locator('..').innerText().catch(() => '');
    out.shown.model_line = badge.replace(/\s+/g, ' ');
    if (shots) await page.screenshot({ path: path.join(shots, 'release_future_wealth.png'), fullPage: true });
    // R5 assumptions, uncertainty and the 12-month coverage limitation are communicated
    const body = await page.locator('[data-testid="stMain"]').innerText();
    out.shown.not_a_forecast = body.includes('This is not a forecast');
    // real-data record: the measured coverage; synthetic-only (public copy): no real-data validation
    out.shown.coverage_warning = (body.match(/12-month 90% ranges contained the outcome only [^.]*\./)
      || body.match(/No real-data validation of long-horizon ranges[^.]*\./) || [''])[0];
    out.shown.sampling_range = (out.shown['Hold it at the end'] || {}).delta;
    await page.getByRole('tab', { name: 'Model sensitivity', exact: true }).click(); await idle(page);
    out.shown.model_uncertainty = await page.getByText('Model uncertainty dominates').count() > 0;
    await page.getByRole('tab', { name: 'Validation', exact: true }).click(); await idle(page);
    out.shown.validation_summary = ((await page.locator('[data-testid="stMain"]').innerText()).match(/What this means for your projection\.[^\n]*/) || [''])[0];
    await page.getByRole('tab', { name: 'Assumptions & export', exact: true }).click(); await idle(page);
    const tail = await page.locator('[data-testid="stMain"]').innerText();
    out.shown.event_order = tail.includes('Event order each month');
    out.shown.recording_disabled = tail.includes('Forecast recording is switched off on this public demo');
    out.shown.record_button = await page.getByRole('button', { name: 'Record this forecast' }).count();
    check('R5 assumptions and uncertainty shown', out.shown.not_a_forecast && out.shown.coverage_warning && out.shown.model_uncertainty
      && out.shown.validation_summary && out.shown.event_order && /\(95%\)/.test(out.shown.sampling_range || ''), out.shown.coverage_warning);
    // R6 Overview without crashes
    await page.locator('[data-testid="stSidebarNav"] a', { hasText: 'Overview' }).first().click(); await idle(page);
    check('R6 Overview opens without an error', !(await broken(page)) && (await page.locator('[data-testid="stMain"] h1').count()) === 1);
    // R7 desktop layout and console
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    check('R7 desktop layout and no browser errors', overflow <= 2 && errors.length === 0, `overflow ${overflow}px, errors ${errors.length}`);
  } catch (e) {
    check('R0 run completed', false, String(e).slice(0, 300));
  }
  out.browser_errors = errors;
  fs.writeFileSync(outFile, JSON.stringify(out, null, 2));
  await browser.close();
})();
