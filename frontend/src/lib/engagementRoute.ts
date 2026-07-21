const CANONICAL_ID = /^[A-Za-z0-9_-]{1,128}$/;

export function parseEngagementRoute(viewRoute: string): {
  id: string;
  sub: string;
  recordId: string;
} | null {
  const parts = viewRoute.split("/");
  const [root, prefix, id = "", sub = "", recordId = ""] = parts;

  if (root !== "" || prefix !== "engagements" || !CANONICAL_ID.test(id)) return null;
  if (parts.length === 3) return { id, sub: "", recordId: "" };
  if (sub === "tasks") {
    if (parts.length === 4) return { id, sub, recordId: "" };
    return parts.length === 5 && CANONICAL_ID.test(recordId)
      ? { id, sub, recordId }
      : null;
  }
  if ((sub === "artifacts" || sub === "settings") && parts.length === 4) {
    return { id, sub, recordId: "" };
  }
  return null;
}
