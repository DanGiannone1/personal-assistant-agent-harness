import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// This harness runs pure TypeScript/Node (no DOM, no React renderer — see
// tsconfig.contract.json). WorkbenchNav.tsx needs a Next.js router and an
// AppAuthProvider context to actually mount, so this checks its *source*: every
// one of the seven host routes must still be wired to a nav item with a stable
// data-testid, so a future Playwright journey can navigate through all of them.
// This checks the navigation contract. Playwright checks the rendered application;
// see docs/guides/local-development.md.
function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

const navSource = readFileSync(
  resolve(__dirname, "..", "src", "components", "workbench", "WorkbenchNav.tsx"),
  "utf8",
);
const assistantSource = readFileSync(
  resolve(__dirname, "..", "src", "components", "AssistantWorkspace.tsx"),
  "utf8",
);

const HOST_ROUTES = ["/engagements", "/home", "/todo", "/calendar", "/reminders", "/settings"];
for (const route of HOST_ROUTES) {
  expect(
    navSource.includes(`navItem("${route}"`),
    `WorkbenchNav must render a nav item for ${route}`,
  );
}

expect(
  navSource.includes('data-testid="nav-assistant"') && navSource.includes('router.push("/assistant")'),
  "WorkbenchNav must render the Assistant entry routing to /assistant",
);

expect(
  navSource.includes('data-testid="personal-nav-section"') &&
    navSource.indexOf('navItem("/home"') < navSource.indexOf('navItem("/engagements"') &&
    navSource.indexOf('data-testid="personal-nav-section"') > navSource.indexOf('navItem("/engagements"') &&
    navSource.indexOf('navItem("/todo"') > navSource.indexOf('data-testid="personal-nav-section"') &&
    navSource.indexOf('navItem("/calendar"') > navSource.indexOf('data-testid="personal-nav-section"') &&
    navSource.indexOf('navItem("/reminders"') > navSource.indexOf('data-testid="personal-nav-section"'),
  "Home must lead the nav, Engagements must follow, and private-work routes must remain under My work",
);

expect(
  assistantSource.includes("state.viewRouteRevision === handledViewRouteRevision.current") &&
    assistantSource.includes("isHostRoute(state.viewRoute)") &&
    assistantSource.includes('router.push("/")'),
  "AI Mode must return every accepted structured host-route request to the host application, including a repeated route",
);

expect(
  assistantSource.includes("const navigateHostView") &&
    assistantSource.includes("onNavigate={navigateHostView}"),
  "AI Mode manual navigation must leave the workspace even when the host route is unchanged",
);

expect(
  assistantSource.includes("artifactPreference?.sessionId === state.sessionId") &&
    assistantSource.includes("sessionId: state.sessionId"),
  "AI Mode artifact visibility preferences must be scoped to the current session",
);
