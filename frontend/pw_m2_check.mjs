// M2 milestone proof (editor mutates, viewer can't, Home aggregates) + the M3
// browser-level acceptance demo: same utterance, different user, different landing.
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = 'http://localhost:3001';
const OUT = '/home/dan/projects/flow/.claude/worktrees/iron-clad-navigation/screenshots/m2';
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const results = [];
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png` });

async function signIn(user, pass) {
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 90000 });
  await page.fill('[data-testid="signin-username"]', user);
  await page.fill('[data-testid="signin-password"]', pass);
  await page.click('[data-testid="signin-submit"]');
  await page.waitForSelector('[data-testid="home-screen"]', { timeout: 60000 });
  return page;
}

// ── [1] dan: Home aggregates; Projects lists both with roles; owner mutates ──
const dan = await signIn('dan', 'dan-demo-1');
const homeProjects = await dan.locator('[data-testid="home-projects"]').count();
await dan.click('[data-testid="nav--projects"]');
await dan.waitForSelector('[data-testid="projects-screen"]', { timeout: 30000 });
await shot(dan, '01-dan-projects-list');
const rows = await dan.locator('[data-testid^="project-row-"]').count();
await dan.locator('[data-testid^="project-row-"]', { hasText: 'Website Launch' }).first().click();
await dan.waitForSelector('[data-testid="project-screen"]', { timeout: 30000 });
await dan.click('[data-testid="add-task-btn"]');
await dan.fill('[data-testid="task-title-input"]', 'M2 owner task via UI');
await dan.click('[data-testid="task-save-btn"]');
await dan.waitForTimeout(1800);
const danSees = await dan.locator('text=M2 owner task via UI').count();
await shot(dan, '02-dan-owner-mutates');
results.push({ step: 'dan: home aggregates + owner mutates', homeProjects, projectRows: rows, taskCreated: danSees > 0 });

// ── [2] sam (viewer): sees the shared task, has NO mutation affordances ──
const sam = await signIn('sam', 'sam-demo-1');
await sam.click('[data-testid="nav--projects"]');
await sam.waitForSelector('[data-testid="projects-screen"]', { timeout: 30000 });
await sam.locator('[data-testid^="project-row-"]', { hasText: 'Website Launch' }).first().click();
await sam.waitForSelector('[data-testid="project-screen"]', { timeout: 30000 });
await sam.waitForTimeout(800);
const samSeesShared = await sam.locator('text=M2 owner task via UI').count();
const samAddBtns = await sam.locator('[data-testid="add-task-btn"], [data-testid="add-event-btn"]').count();
const samDeletes = await sam.locator('[data-testid^="task-delete-"]').count();
await shot(sam, '03-sam-viewer-readonly');
results.push({ step: 'sam viewer', seesSharedTask: samSeesShared > 0, addAffordances: samAddBtns, deleteAffordances: samDeletes });

// ── [3] ava: membership trims the world (no Website Launch anywhere) ──
const ava = await signIn('ava', 'ava-demo-1');
await ava.click('[data-testid="nav--projects"]');
await ava.waitForSelector('[data-testid="projects-screen"]', { timeout: 30000 });
const avaSeesWebsite = await ava.locator('text=Website Launch').count();
const avaRows = await ava.locator('[data-testid^="project-row-"]').count();
await shot(ava, '04-ava-membership-trimmed');
results.push({ step: 'ava membership', seesWebsiteLaunch: avaSeesWebsite, projectRows: avaRows });

// ── [4] THE ACCEPTANCE DEMO: same utterance, different user, different landing ──
const ask = async (page, name) => {
  await page.fill('textarea', 'take me to the launch tasks');
  await page.keyboard.press('Enter');
  await page.waitForSelector('[data-testid="project-screen"]', { timeout: 90000 });
  await page.waitForTimeout(1000);
  await shot(page, name);
  return (await page.locator('[data-testid="project-screen"]').innerText()).slice(0, 400);
};
const danLanding = await ask(dan, '05-dan-launch-landing');
const avaLanding = await ask(ava, '06-ava-launch-landing');
results.push({
  step: 'ACCEPTANCE: same utterance, different landing',
  dan: danLanding.includes('Website Launch') ? 'Website Launch' : danLanding.slice(0, 60),
  ava: avaLanding.includes('Product Launch') ? 'Product Launch' : avaLanding.slice(0, 60),
});

const pass =
  results[0].taskCreated && results[0].homeProjects > 0 &&
  results[1].seesSharedTask && results[1].addAffordances === 0 && results[1].deleteAffordances === 0 &&
  results[2].seesWebsiteLaunch === 0 &&
  results[3].dan === 'Website Launch' && results[3].ava === 'Product Launch';
console.log(JSON.stringify({ M2_M3_VERDICT: pass ? 'PASS' : 'FAIL', results }, null, 2));
await browser.close();
process.exit(pass ? 0 : 1);
