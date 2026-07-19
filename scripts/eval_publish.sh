#!/usr/bin/env bash
# Publish eval run bundles to Blob and run metrics to Application Insights (dev).
# Usage: EVAL_STORAGE_ACCOUNT=<name> EVAL_APPINSIGHTS_CONNECTION="<conn>" \
#        scripts/eval_publish.sh <results.json> [<results.json> ...]
# Requires: az CLI logged in with Storage Blob Data Contributor on the account.
set -euo pipefail

: "${EVAL_STORAGE_ACCOUNT:?EVAL_STORAGE_ACCOUNT is required}"
: "${EVAL_APPINSIGHTS_CONNECTION:?EVAL_APPINSIGHTS_CONNECTION is required}"

IKEY=$(sed -n 's/.*InstrumentationKey=\([^;]*\).*/\1/p' <<<"$EVAL_APPINSIGHTS_CONNECTION")
INGEST=$(sed -n 's/.*IngestionEndpoint=\([^;]*\).*/\1/p' <<<"$EVAL_APPINSIGHTS_CONNECTION")

for RESULTS in "$@"; do
  RUN_ID=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['runId'])" "$RESULTS")
  echo "publishing $RUN_ID"

  az storage blob upload --account-name "$EVAL_STORAGE_ACCOUNT" --container-name eval-runs \
    --name "$RUN_ID/results.json" --file "$RESULTS" --auth-mode login --overwrite --only-show-errors

  JUDGE="$(dirname "$RESULTS")/judge.json"
  if [ -f "$JUDGE" ]; then
    az storage blob upload --account-name "$EVAL_STORAGE_ACCOUNT" --container-name eval-runs \
      --name "$RUN_ID/judge.json" --file "$JUDGE" --auth-mode login --overwrite --only-show-errors
  fi

  python3 - "$RESULTS" "$IKEY" "$INGEST" <<'PYEOF'
import json, sys, urllib.request
from datetime import datetime, timezone

results_path, ikey, ingest = sys.argv[1], sys.argv[2], sys.argv[3]
report = json.load(open(results_path))
now = datetime.now(timezone.utc).isoformat()

def envelope(name, properties, measurements):
    return {
        "name": "Microsoft.ApplicationInsights.Event", "time": now, "iKey": ikey,
        "data": {"baseType": "EventData", "baseData": {
            "ver": 2, "name": name, "properties": properties, "measurements": measurements}},
    }

common = {"runId": report["runId"], "model": report.get("model", ""),
          "harness": report.get("harness", ""), "sourceRevision": report.get("sourceRevision", ""),
          "environment": report.get("environment", "")}

items = [envelope("eval_run", common, {
    "passed": report["summary"]["passed"],
    "failed": len(report["summary"]["failed"]),
    "totalLatencyMs": sum(r.get("latencyMs", 0) for r in report["results"]),
})]
for r in report["results"]:
    tools = [e.get("tool_call_name") for e in r.get("events", []) if e.get("type") == "TOOL_CALL_START"]
    items.append(envelope("eval_case", {**common, "caseId": r["id"], "pass": str(r["pass"]),
                                        "tools": ",".join(t for t in tools if t)},
                          {"latencyMs": r.get("latencyMs", 0), "toolCalls": len(tools)}))

body = "\n".join(json.dumps(i) for i in items).encode()
req = urllib.request.Request(ingest.rstrip("/") + "/v2/track", data=body,
                             headers={"Content-Type": "application/x-json-stream"})
resp = json.load(urllib.request.urlopen(req, timeout=30))
print(f"app insights: accepted {resp.get('itemsAccepted')}/{resp.get('itemsReceived')}")
PYEOF
done
