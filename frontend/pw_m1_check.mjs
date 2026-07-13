// M1 milestone proof: two users sign in and see separate worlds (spec M1 checkpoint).
// Run: node pw_m1_check.mjs  (stack must be up on :3001/:8002/:8082)
import { chromium } from 'playwright';
import { mkdirSync } from 'node:fs';

const BASE = 'http://localhost:3001';
const OUT = '/home/dan/projects/flow/.claude/worktrees/iron-clad-navigation/screenshots/m1';
mkdirSync(OUT, { recursive: true });

const browser = await chromium.launch();
const results = [];
const shot = (page, name) => page.screenshot({ path: `${OUT}/${name}.png` });

async function signIn(ctx, user, pass) {
  const page = await ctx.newPage();
  await page.goto(BASE, { waitUntil: 'networkidle', timeout: 60000 });
  await page.fill('[data-testid="signin-username"]', user);
  await page.fill('[data-testid="signin-password"]', pass);
  await page.click('[data-testid="signin-submit"]');
  return page;
}

// 1) Dan signs in, sees his world, creates a task manually.
const danCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const dan = await signIn(danCtx, 'dan', 'dan-demo-1');
await dan.waitForSelector('[data-testid="workbench-app"]', { timeout: 30000 });
// Wait for real app-state content (not just the shell) — cold dev-server compiles are slow.
await dan.waitForSelector('[data-testid="home-screen"]', { timeout: 45000 });
await shot(dan, '01-dan-signed-in');
const danChip = await dan.locator('[data-testid="user-chip"]').isVisible().catch(() => false);
await dan.click('[data-testid="nav--todo"]');
await dan.waitForSelector('[data-testid="todo-screen"]', { timeout: 30000 });
await dan.click('[data-testid="add-task-btn"]');
await dan.fill('[data-testid="task-title-input"]', 'Dan M1 milestone task');
await dan.click('[data-testid="task-save-btn"]');
await dan.waitForTimeout(1500);
const danSees = await dan.locator('text=Dan M1 milestone task').count();
await shot(dan, '02-dan-created-task');
results.push({ step: 'dan signs in + creates task', chipVisible: danChip, taskVisible: danSees > 0 });

// 2) Ava signs in (separate context = separate tab/user), must NOT see Dan's task.
const avaCtx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
const ava = await signIn(avaCtx, 'ava', 'ava-demo-1');
await ava.waitForSelector('[data-testid="workbench-app"]', { timeout: 30000 });
await ava.waitForSelector('[data-testid="home-screen"]', { timeout: 45000 });
await ava.click('[data-testid="nav--todo"]');
await ava.waitForSelector('[data-testid="todo-screen"]', { timeout: 30000 });
const avaSeesDans = await ava.locator('text=Dan M1 milestone task').count();
const avaSeesProbe = await ava.locator('text=Dan-only probe task').count();
await shot(ava, '03-ava-separate-world');
results.push({ step: 'ava separate world', seesDanTask: avaSeesDans, seesDanProbe: avaSeesProbe });

// 3) Bad password fails loud.
const badCtx = await browser.newContext();
const bad = await signIn(badCtx, 'sam', 'wrong-password');
await bad.waitForSelector('[data-testid="signin-error"]', { timeout: 15000 });
const errText = await bad.locator('[data-testid="signin-error"]').innerText();
await shot(bad, '04-bad-password');
results.push({ step: 'bad password', error: errText.slice(0, 60) });

// 4) Sign-out returns to the gate.
await dan.click('[data-testid="signout-btn"]');
await dan.waitForSelector('[data-testid="signin-submit"]', { timeout: 15000 });
await shot(dan, '05-signed-out');
results.push({ step: 'sign-out', gateReturned: true });

const pass = results[0].taskVisible && results[1].seesDanTask === 0 && results[1].seesDanProbe === 0;
console.log(JSON.stringify({ M1_VERDICT: pass ? 'PASS' : 'FAIL', results }, null, 2));
await browser.close();
process.exit(pass ? 0 : 1);
