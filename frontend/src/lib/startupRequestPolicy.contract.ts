import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { STARTUP_REQUEST_TIMEOUT_MS } from "./startupRequestPolicy";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

function source(relativePath: string): string {
  return readFileSync(resolve(__dirname, "..", relativePath), "utf8");
}

function functionRegion(sourceText: string, declaration: string, nextDeclaration: string): string {
  const start = sourceText.indexOf(declaration);
  const end = sourceText.indexOf(nextDeclaration, start + declaration.length);
  expect(start >= 0 && end > start, `could not locate ${declaration}`);
  return sourceText.slice(start, end);
}

const appAuthSource = source("src/lib/appAuth.ts");
const apiSource = source("src/lib/api.ts");
const hookSource = source("src/hooks/useAgentSession.ts");
const sessionManagerSource = source("../session_manager.py");

const fetchMe = functionRegion(appAuthSource, "export async function fetchMe", "export async function login");
const getSession = functionRegion(apiSource, "export async function getSession", "export async function createSession");
const createSession = functionRegion(apiSource, "export async function createSession", "export async function uploadFile");
const restoreStoredSession = functionRegion(hookSource, "const restoreStoredSession", "const startSession");
const startSession = functionRegion(hookSource, "const startSession", "useEffect(() => { startSession(); }");
const createSessionBackend = functionRegion(sessionManagerSource, "async def create_session", "def session_owner");

expect(
  STARTUP_REQUEST_TIMEOUT_MS === 60_000,
  "startup request budget must remain 60 seconds",
);

for (const [name, region] of [
  ["fetchMe", fetchMe],
  ["getSession", getSession],
  ["createSession", createSession],
] as const) {
  const policyUses = region.match(/AbortSignal\.timeout\(STARTUP_REQUEST_TIMEOUT_MS\)/g) ?? [];
  expect(
    policyUses.length === 1,
    `${name} must apply exactly one startup request timeout`,
  );
  expect(!region.includes("15_000"), `${name} must not use the former 15-second timeout`);
}

expect(
  !hookSource.includes("SESSION_TIMEOUT_MS"),
  "the session hook must not reintroduce a separate session timeout",
);
expect(
  !/withTimeout\s*\(\s*getSession\s*\(/.test(restoreStoredSession)
    && !/withTimeout\s*\(\s*createSession\s*\(/.test(startSession),
  "the session hook must not race get/create requests against a separate timeout",
);

const readTimeout = createSessionBackend.match(/timeout=httpx\.Timeout\([\s\S]*?\bread\s*=\s*(\d+(?:\.\d+)?)/);
if (readTimeout === null) throw new Error("create_session must declare an HTTP read timeout");
expect(
  Number(readTimeout[1]) * 1_000 < STARTUP_REQUEST_TIMEOUT_MS,
  "browser startup policy must outlast the runtime-create read timeout",
);
