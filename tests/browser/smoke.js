// Browser workflow checks for the Quant Lab dashboard (Suite L).
//
//   node tests/browser/smoke.js http://127.0.0.1:8765 [screenshot-folder]
//
// The server must already be running with synthetic data as the default source
// (tests/browser/run.sh starts one). Nothing here contacts a market-data provider.
// Exit code 0 = every check passed; 1 = at least one failed.
const { chromium } = require('playwright');
const fs = require('fs');
const os = require('os');
const path = require('path');

const base = (process.argv[2] || 'http://127.0.0.1:8765').replace(/\/$/, '');
const shots = process.argv[3] || '';
const results = [];
const check = (id, name, pass, note = '') => {
  results.push({ id, name, pass: !!pass, note });
  console.log(`${pass ? 'PASS' : 'FAIL'} ${id} ${name}${note ? ' | ' + note : ''}`);
};
// Engine values computed independently of the dashboard, for the exact-value checks (L05, L06).
const EXPECTED = JSON.parse(require('child_process').execFileSync(
  process.env.QL_PYTHON || 'python', [require('path').join(__dirname, 'expected_values.py')]).toString());
const idle = async p => {
  await p.waitForTimeout(700);
  await p.waitForFunction(() => !document.querySelector('[data-testid="stStatusWidget"]'), null, { timeout: 120000 }).catch(() => {});
  await p.waitForTimeout(700);
};
const open = async (p, route) => {
  await p.goto(base + route);
  await p.waitForSelector('[data-testid="stMain"] h1', { timeout: 120000 });
  await idle(p);
};
const broken = p => p.locator('[data-testid="stException"]').count();
const metric = async (p, label) =>
  (await p.locator('[data-testid="stMetric"]', { hasText: label }).first().locator('[data-testid="stMetricValue"]').innerText()).trim();
const spin = (p, name) => p.getByRole('spinbutton', { name, exact: true });
const setv = async (p, name, v) => { await spin(p, name).fill(String(v)); await spin(p, name).press('Enter'); await idle(p); };
const PAGES = [
  ['/', 'Overview'], ['/invest', 'Investment Lab'], ['/market', 'Market Explorer'], ['/strategy', 'Strategy Lab'],
  ['/backtest', 'Backtesting'], ['/risk', 'Risk Analytics'], ['/monte_carlo', 'Monte Carlo'], ['/stress', 'Stress Test'],
  ['/research', 'Research & Reporting'],
];

(async () => {
  const browser = await chromium.launch();
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, acceptDownloads: true });
  const page = await ctx.newPage();
  const consoleErrors = [];
  page.on('pageerror', e => consoleErrors.push(String(e).slice(0, 160)));

  // L01 home page and navigation: every page reachable from the sidebar, no exception box.
  await open(page, '/');
  const links = await page.locator('[data-testid="stSidebarNav"] a').allInnerTexts();
  check('L01', 'home page lists all nine pages', PAGES.every(([, t]) => links.some(l => l.includes(t))), links.length + ' links');
  let failures = [];
  for (const [, title] of PAGES) {
    await page.locator('[data-testid="stSidebarNav"] a', { hasText: title }).first().click();
    await idle(page);
    if (await broken(page)) failures.push(title);
  }
  check('L02', 'sidebar navigation renders every page without an error box', failures.length === 0, failures.join(', '));

  // L03 deep links in a brand-new browser context (no session), each with the shared sidebar.
  failures = [];
  for (const [route, title] of PAGES) {
    const fresh = await browser.newContext({ viewport: { width: 1440, height: 900 } });
    const q = await fresh.newPage();
    await open(q, route);
    const nav = await q.locator('[data-testid="stSidebarNav"] a').count();
    const badge = await q.locator('.ql-badge').count();
    if ((await broken(q)) || nav < 9 || (route !== '/research' && badge < 1)) failures.push(`${route} (nav ${nav}, badge ${badge})`);
    await fresh.close();
    void title;
  }
  check('L03', 'direct links work on a fresh session', failures.length === 0, failures.join('; '));

  // L04 data-source label: synthetic data is always announced as synthetic.
  await open(page, '/invest');
  const badgeText = await page.locator('.ql-badge').first().innerText();
  const warned = await page.getByText('not market history').count();
  check('L04', 'synthetic data is labelled as synthetic', /SYNTHETIC/.test(badgeText) && warned >= 1, badgeText);

  // L05 refresh keeps the page and its results (URL-addressable, no crash).
  const before = await metric(page, 'Final value');
  await page.reload(); await page.waitForSelector('[data-testid="stMetric"]', { timeout: 120000 }); await idle(page);
  const after = await metric(page, 'Final value');
  check('L05', 'browser refresh reproduces the engine value', before === after && after === EXPECTED.default
        && !(await broken(page)), `${before} -> ${after} (engine ${EXPECTED.default})`);

  // L06 editing an allocation updates results; L07 invalid input is refused and recovers.
  await setv(page, 'SYN1 in A (%)', 30);
  // The rerun can start after idle()'s fixed delay on a slow runner: wait (bounded) for a new value.
  // The check is the engine's exact value for the edited portfolio (expected_values.py), not "any change".
  let edited = await metric(page, 'Final value');
  for (let i = 0; i < 30 && edited !== EXPECTED.l06; i++) { await page.waitForTimeout(1000); await idle(page); edited = await metric(page, 'Final value'); }
  check('L06', 'editing an allocation shows the engine value for the new allocation',
        edited === EXPECTED.l06 && edited !== after, `${after} -> ${edited} (engine ${EXPECTED.l06})`);
  await setv(page, 'SYN2 in A (%)', 95);
  const refused = (await page.getByText('Leverage is not supported').count()) >= 1 && (await page.locator('[data-testid="stMetric"]').count()) === 0;
  await setv(page, 'SYN2 in A (%)', 40);
  const recovered = (await page.locator('[data-testid="stMetric"]').count()) > 0 && !(await broken(page));
  check('L07', 'over-allocation is refused, then recovers when corrected', refused && recovered, `refused ${refused}, recovered ${recovered}`);

  // L08 rapid repeated edits settle on the last value (no stale result).
  for (const v of [10, 20, 30, 40, 25]) { await spin(page, 'SYN1 in A (%)').fill(String(v)); await spin(page, 'SYN1 in A (%)').press('Enter'); }
  await idle(page); await idle(page);
  const rapid = await metric(page, 'Final value');
  await setv(page, 'SYN1 in A (%)', 26); await setv(page, 'SYN1 in A (%)', 25);
  check('L08', 'rapid edits settle on the last input', rapid === (await metric(page, 'Final value')), rapid);

  // L09 tabs all render content.
  failures = [];
  const tabs = await page.getByRole('tab').allInnerTexts();
  for (const name of tabs) {
    await page.getByRole('tab', { name, exact: true }).click(); await idle(page);
    if (await broken(page)) failures.push(name);
  }
  check('L09', 'every Investment Lab tab renders', tabs.length >= 5 && failures.length === 0, tabs.join(' / '));

  // L10 save, reload the saved file, same result; L11 exports agree with the screen.
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'ql-browser-'));
  const saveTab = tabs.find(t => /save/i.test(t));
  await page.getByRole('tab', { name: saveTab, exact: true }).click(); await idle(page);
  const grab = async label => {
    const [d] = await Promise.all([page.waitForEvent('download', { timeout: 60000 }), page.getByRole('button', { name: label }).first().click()]);
    const file = path.join(tmp, d.suggestedFilename()); await d.saveAs(file); return file;
  };
  const buttons = await page.locator('[data-testid="stDownloadButton"] button').allInnerTexts();
  const saved = {};
  for (const label of buttons) saved[label] = await grab(label).catch(e => 'ERR ' + e.message);
  const pick = re => Object.entries(saved).find(([k]) => re.test(k))?.[1];
  const shown = await metric(page, 'Final value');
  const record = JSON.parse(fs.readFileSync(pick(/analysis/i) || pick(/JSON/), 'utf8'));
  const first = Object.keys(record.results || {})[0];
  const exported = first ? Math.round(record.results[first].final_value).toLocaleString('en-US') : 'n/a';
  check('L11', 'exported final value equals the value on screen', exported === shown, `${buttons.length} downloads; file ${exported}, screen ${shown}`);
  const pick_html = pick(/HTML/i);
  const html = fs.readFileSync(pick_html, 'utf8');
  check('L12', 'HTML report is self-contained and carries the synthetic banner', html.includes('SYNTHETIC DATA') && !/<script|https?:\/\//i.test(html), html.length + ' bytes');
  const portfolioFile = pick(/portfolio/i);
  await setv(page, 'SYN1 in A (%)', 5);
  await page.getByText('Load a saved portfolio file').click();
  await page.locator('[data-testid="stMain"] input[type=file]').setInputFiles(portfolioFile); await idle(page);
  await page.getByRole('button', { name: 'Load into the builder' }).click(); await idle(page); await idle(page);
  const restored = await metric(page, 'Final value');
  check('L10', 'saving and reloading a portfolio reproduces the result', restored === shown, `saved ${shown}, reloaded ${restored}`);

  // L13 a corrupt portfolio file is refused with a message, the page keeps working.
  const corrupt = path.join(tmp, 'corrupt.json'); fs.writeFileSync(corrupt, '{"schema": "quantlab.investment_lab/1", "portfolios": {"x": {"weights": {"SYN1": "lots"}}}');
  await page.locator('[data-testid="stMain"] input[type=file]').setInputFiles(corrupt); await idle(page);
  await page.getByRole('button', { name: 'Load into the builder' }).click(); await idle(page);
  const complained = await page.locator('[data-testid="stAlert"]').filter({ hasText: 'could not be loaded' }).count();
  check('L13', 'a corrupt portfolio file is refused with a message', complained >= 1 && !(await broken(page)) && (await page.locator('[data-testid="stMetric"]').count()) > 0);

  // L14 laptop and phone layouts: no horizontal page scroll, key numbers visible.
  for (const [name, w, h] of [['laptop', 1280, 720], ['phone', 390, 844]]) {
    const c = await browser.newContext({ viewport: { width: w, height: h } });
    const q = await c.newPage(); await open(q, '/invest');
    const overflow = await q.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    const visible = await q.locator('[data-testid="stMetricValue"]').first().isVisible().catch(() => false);
    const clipped = await q.locator('[data-testid="stMetricLabel"]').evaluateAll(els => els.filter(e => e.scrollWidth > e.clientWidth + 1).length);
    check('L14', `${name} layout (${w}x${h})`, overflow <= 2 && visible && clipped === 0, `horizontal overflow ${overflow}px, clipped labels ${clipped}`);
    if (shots) await q.screenshot({ path: path.join(shots, `invest_${name}.png`) });
    await c.close();
  }

  // L15 basic keyboard and accessibility checks.
  await open(page, '/invest');
  const unnamed = await page.evaluate(() => [...document.querySelectorAll('[data-testid="stMain"] input, [data-testid="stMain"] button, [data-testid="stMain"] [role=tab]')]
    .filter(e => e.offsetParent && !(e.getAttribute('aria-label') || e.labels?.length || e.textContent?.trim() || e.title))
    .map(e => `${e.tagName.toLowerCase()}[${e.getAttribute('data-testid') || e.type || ''}]`));
  await page.keyboard.press('Tab'); await page.keyboard.press('Tab'); await page.keyboard.press('Tab');
  const focused = await page.evaluate(() => document.activeElement && document.activeElement !== document.body ? document.activeElement.tagName : '');
  const h1 = await page.locator('[data-testid="stMain"] h1').count();
  const lang = await page.evaluate(() => document.documentElement.lang || '');
  check('L15', 'controls are named, keyboard focus moves, one page heading', unnamed.length === 0 && !!focused && h1 === 1, `unnamed controls ${unnamed.length} ${unnamed.join(',')}, focus on ${focused}, h1 ${h1}, lang "${lang}"`);

  // L16 other analysis pages react to input.
  await open(page, '/stress');
  const grids = await page.locator('[data-testid="stDataFrame"]').count();
  check('L16', 'stress page shows scenario and per-holding results', grids >= 2 && (await page.getByText('hypothetical').count()) >= 1 && !(await broken(page)), grids + ' tables');
  await open(page, '/monte_carlo');
  check('L17', 'Monte Carlo page labels itself as not a forecast', (await page.getByText(/not a forecast|not forecasts|not a prediction/i).count()) >= 1 && !(await broken(page)));
  // Remediation checks (QA-026, QA-024, QA-030, QA-022).
  await open(page, '/invest');
  await page.waitForSelector('[data-testid="stMetric"]', { timeout: 120000 }); await idle(page);
  if (shots) await page.screenshot({ path: path.join(shots, 'invest_top.png') });
  await page.getByRole('tab', { name: 'Risk insights', exact: true }).click(); await idle(page);
  await page.locator('[data-testid="stSelectbox"]', { hasText: 'Portfolio to inspect' }).waitFor({ timeout: 60000 });
  const inspectBox = page.locator('[data-testid="stSelectbox"]', { hasText: 'Portfolio to inspect' });
  await inspectBox.getByRole('combobox').click();
  await page.getByRole('option', { name: 'Portfolio B', exact: true }).click(); await idle(page);
  const inspected = await page.getByText("Portfolio B's estimated volatility").count();
  const sideBySide = await page.getByText('All compared portfolios, side by side').count();
  if (shots) await page.screenshot({ path: path.join(shots, 'invest_risk_insights.png'), fullPage: true });
  check('L19', 'Investment Lab risk insights inspect any portfolio and compare all', inspected >= 1 && sideBySide === 1 && !(await broken(page)));

  await page.locator('[data-testid="stSidebarNav"] a', { hasText: 'Risk Analytics' }).first().click(); await idle(page);
  const chosen = await page.locator('[data-testid="stSelectbox"]', { hasText: 'Portfolio to analyse' }).getByRole('combobox').inputValue();
  const fromLab = await page.getByText('Target weights from the Investment Lab').count();
  const modelBadge = await page.getByText('MODEL: FIXED WEIGHTS').count();
  if (shots) await page.screenshot({ path: path.join(shots, 'risk_shared_portfolio.png'), fullPage: true });
  check('L20', 'Risk Analytics analyses the Investment Lab portfolio and names its model',
        /Investment Lab: Portfolio A/.test(chosen) && fromLab >= 1 && modelBadge >= 1, chosen.replace(/\s+/g, ' ').slice(0, 80));

  await page.locator('[data-testid="stSidebarNav"] a', { hasText: 'Monte Carlo' }).first().click(); await idle(page);
  const range = await page.locator('[data-testid="stMetricDelta"]').filter({ hasText: '(95%)' }).count();
  await page.getByRole('tab', { name: 'How much the answer depends on the model', exact: true }).click(); await idle(page);
  const rows = await page.locator('[data-testid="stDataFrame"]:visible').count();
  const reading = await page.getByText("None of these rows is the 'right' one.", { exact: false }).count();
  if (shots) await page.screenshot({ path: path.join(shots, 'monte_carlo_model_dependence.png'), fullPage: true });
  check('L21', 'Monte Carlo shows sampling ranges and model dependence', range >= 2 && rows >= 1 && reading >= 1, `ranges ${range}`);

  const reportText = html.replace(/<[^>]+>/g, ' ');
  check('L22', 'Investment Lab report states findings, allocations, period and reproducibility',
        ['Key findings', 'Portfolios and allocations', 'Evaluation period', 'Compared with the alternatives',
         'Limitations', 'Reproducibility', 'Dataset fingerprint'].every(t => reportText.includes(t)) && !/\bnan\b/i.test(reportText));
  if (shots) fs.copyFileSync(pick_html, path.join(shots, 'investment_lab_report.html'));

  // Future Wealth (Quant Lab 3.0): the forward-looking mode of the Investment Lab.
  await open(page, '/invest');
  await page.waitForSelector('[data-testid="stMetric"]', { timeout: 120000 }); await idle(page);
  await page.getByRole('radio', { name: 'Future wealth' }).click(); await idle(page);
  await page.waitForSelector('text=FUTURE WEALTH', { timeout: 120000 }); await idle(page);
  const fwMedian = await metric(page, 'Median after 10 yr').catch(() => '');
  const fwHold = await metric(page, 'Hold it at the end').catch(() => '');
  if (shots) await page.screenshot({ path: path.join(shots, 'future_wealth.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Model sensitivity', exact: true }).click(); await idle(page);
  const dominates = await page.getByText('Model uncertainty dominates').count();
  if (shots) await page.screenshot({ path: path.join(shots, 'future_wealth_sensitivity.png'), fullPage: true });
  await page.getByRole('tab', { name: 'Assumptions & export', exact: true }).click(); await idle(page);
  await page.getByRole('button', { name: 'Record this forecast' }).click(); await idle(page);
  const recorded = await page.getByText('Recorded forecast').count();
  check('L23', 'Future Wealth projects a plan, explains model uncertainty and records a forecast',
        /^\$[\d.,]+[kM]?$/.test(fwMedian) && /%$/.test(fwHold) && dominates >= 1 && recorded >= 1 && !(await broken(page)),
        `median ${fwMedian}, hold ${fwHold}`);

  check('L18', 'no uncaught browser errors during the run', consoleErrors.length === 0, consoleErrors.slice(0, 3).join(' || '));

  await browser.close();
  const failed = results.filter(r => !r.pass);
  if (shots) fs.writeFileSync(path.join(shots, 'browser_results.json'), JSON.stringify(results, null, 2));
  console.log(`\n${results.length - failed.length} passed, ${failed.length} failed`);
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('ERROR', e); process.exit(2); });
