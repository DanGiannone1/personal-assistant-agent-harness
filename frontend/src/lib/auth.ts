import {
  EventType,
  InteractionRequiredAuthError,
  PublicClientApplication,
  type AccountInfo,
  type AuthenticationResult,
  type Configuration,
} from "@azure/msal-browser";

import { getUserToken } from "./session";

const authEnabled = (process.env.NEXT_PUBLIC_AUTH_ENABLED || "").toLowerCase() === "true";
const tenantId = process.env.NEXT_PUBLIC_ENTRA_TENANT_ID || "";
const clientId = process.env.NEXT_PUBLIC_ENTRA_CLIENT_ID || "";
const apiClientId =
  process.env.NEXT_PUBLIC_ENTRA_API_CLIENT_ID ||
  process.env.NEXT_PUBLIC_ENTRA_BACKEND_CLIENT_ID ||
  "";

const configuredScopes = (process.env.NEXT_PUBLIC_ENTRA_API_SCOPES || "")
  .split(",")
  .map((value) => value.trim())
  .filter(Boolean);

const authScopes = configuredScopes.length > 0
  ? configuredScopes
  : apiClientId
    ? [`api://${apiClientId}/access_as_user`]
    : [];

let msalInstancePromise: Promise<PublicClientApplication> | null = null;
let redirectHandledPromise: Promise<AuthenticationResult | null> | null = null;

function getRedirectUri(): string {
  if (process.env.NEXT_PUBLIC_ENTRA_REDIRECT_URI) {
    return process.env.NEXT_PUBLIC_ENTRA_REDIRECT_URI;
  }
  if (typeof window !== "undefined") {
    return window.location.origin;
  }
  return "http://localhost:3000";
}

function getMsalConfig(): Configuration {
  return {
    auth: {
      authority: `https://login.microsoftonline.com/${tenantId}`,
      clientId,
      redirectUri: getRedirectUri(),
    },
    cache: {
      cacheLocation: "sessionStorage",
    },
    system: {
      allowPlatformBroker: false,
    },
  };
}

function ensureConfigured(): void {
  if (!authEnabled) return;
  if (!tenantId || !clientId || authScopes.length === 0) {
    throw new Error(
      "Authentication is enabled but Entra frontend configuration is incomplete.",
    );
  }
}

async function getMsalInstance(): Promise<PublicClientApplication | null> {
  if (!authEnabled) return null;
  ensureConfigured();

  if (!msalInstancePromise) {
    msalInstancePromise = (async () => {
      const instance = new PublicClientApplication(getMsalConfig());
      await instance.initialize();
      instance.addEventCallback((event) => {
        if (
          (event.eventType === EventType.LOGIN_SUCCESS ||
            event.eventType === EventType.ACQUIRE_TOKEN_SUCCESS) &&
          event.payload &&
          "account" in event.payload &&
          event.payload.account
        ) {
          instance.setActiveAccount(event.payload.account);
        }
      });
      return instance;
    })();
  }

  const instance = await msalInstancePromise;
  if (!redirectHandledPromise) {
    redirectHandledPromise = instance.handleRedirectPromise().then((result) => {
      if (result?.account) {
        instance.setActiveAccount(result.account);
      } else if (!instance.getActiveAccount()) {
        const account = instance.getAllAccounts()[0];
        if (account) instance.setActiveAccount(account);
      }
      return result;
    }).finally(() => {
      redirectHandledPromise = null;
    });
  }
  await redirectHandledPromise;
  return instance;
}

async function getActiveAccount(): Promise<AccountInfo | null> {
  const instance = await getMsalInstance();
  if (!instance) return null;
  return instance.getActiveAccount() || instance.getAllAccounts()[0] || null;
}

export function isBrowserAuthEnabled(): boolean {
  return authEnabled;
}

export async function getSignedInUserLabel(): Promise<string | null> {
  const account = await getActiveAccount();
  if (!account) return null;
  return account.name || account.username || account.homeAccountId || "Signed-in user";
}

export async function signIn(): Promise<void> {
  const instance = await getMsalInstance();
  if (!instance) return;
  await instance.loginRedirect({ scopes: authScopes });
}

export async function signOut(): Promise<void> {
  const instance = await getMsalInstance();
  if (!instance) return;
  const account = instance.getActiveAccount() || instance.getAllAccounts()[0] || undefined;
  await instance.logoutRedirect({ account });
}

export async function getAccessToken(): Promise<string> {
  if (!authEnabled) return "";

  const instance = await getMsalInstance();
  if (!instance) return "";

  const account = instance.getActiveAccount() || instance.getAllAccounts()[0];
  if (!account) {
    throw new Error("Authentication required.");
  }

  try {
    const result = await instance.acquireTokenSilent({
      account,
      scopes: authScopes,
    });
    if (result.account) instance.setActiveAccount(result.account);
    return result.accessToken;
  } catch (error) {
    if (error instanceof InteractionRequiredAuthError) {
      await instance.acquireTokenRedirect({
        account,
        scopes: authScopes,
      });
      throw new Error("Authentication required.");
    }
    throw error;
  }
}

export async function buildAuthHeaders(headersInit?: HeadersInit): Promise<Headers> {
  const headers = new Headers(headersInit);

  // App-level user token (spec F1). The single seam that authenticates the signed-in user
  // on every REST + SSE call — independent of the MSAL caller-auth below, so it attaches
  // whether or not Entra sign-in is enabled.
  const userToken = getUserToken();
  if (userToken) headers.set("x-user-token", userToken);

  if (!authEnabled) return headers;

  const accessToken = await getAccessToken();
  if (!accessToken) {
    throw new Error("Authentication required.");
  }
  headers.set("Authorization", `Bearer ${accessToken}`);
  return headers;
}
