import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { evaluateCase, evaluateWorkflow } from "../scripts/mvp_evidence.mjs";
import { MVP_EVAL_MANIFEST } from "../scripts/mvp_eval_manifest.mjs";
import { loadMvpJudgeRubric, summarizeMvpJudge, validateMvpJudgeRecord, validateMvpJudgeRubric } from "../scripts/mvp_judge.mjs";
import { buildMvpScorecard, renderMvpScorecard, summarizeWaza, WAZA_GATE_TASK_IDS } from "../scripts/mvp_scorecard.mjs";

const start = (run = "run-1") => ({ type: "RUN_STARTED", run_id: run, thread_id: "thread-1" });
const finish = (run = "run-1") => ({ type: "RUN_FINISHED", run_id: run, thread_id: "thread-1" });
const text = (value, id = "message-1") => [
  { type: "TEXT_MESSAGE_START", message_id: id, role: "assistant" },
  { type: "TEXT_MESSAGE_CONTENT", message_id: id, delta: value },
  { type: "TEXT_MESSAGE_END", message_id: id },
];
const tool = ({ id, name, args, result, navigation }) => [
  { type: "TOOL_CALL_START", tool_call_id: id, tool_call_name: name },
  { type: "TOOL_CALL_ARGS", tool_call_id: id, delta: JSON.stringify(args) },
  { type: "TOOL_CALL_RESULT", tool_call_id: id, result },
  ...(navigation ? [{ type: "NAVIGATION_RESOLVED", ...navigation }] : []),
  { type: "TOOL_CALL_END", tool_call_id: id },
];
const rawTool = ({ run = "run-1", id, name, args, output = "model-visible facts", result }) => ({
  kind: "product_tool_execution",
  run_id: run,
  tool_call_id: id,
  tool: name,
  arguments: args,
  model_visible_output: output,
  product_result: result,
});
const wazaGate = (overrides = {}) => ({
  schemaVersion: "1.2",
  eval_id: "waza-run",
  skill: "engagement-meeting-prep",
  config: { model_id: "claude-sonnet-4.6", engine_type: "copilot-sdk" },
  summary: { total_tests: 4, succeeded: 4, failed: 0, errors: 0, skipped: 0 },
  tasks: WAZA_GATE_TASK_IDS.map((test_id) => ({ test_id, status: "passed" })),
  csaMvpProvenance: {
    runner: "scripts/waza_eval.sh",
    wazaVersion: "0.38.3",
    tag: "gate",
    eval: "tests/evals/waza/engagement-meeting-prep/eval.yaml",
    sourceRevision: "abc",
    sourceRevisionAfter: "abc",
    sourceDirtyBefore: false,
    sourceDirtyAfter: false,
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
  },
  ...overrides,
});

function canonicalAtomicResults(fixture) {
  return MVP_EVAL_MANIFEST.atomicCaseIds.map((id) => ({ id, pass: true, fixture }));
}

function canonicalWorkflowResults(fixture, reviewStatus = "REVIEW_REQUIRED") {
  return MVP_EVAL_MANIFEST.workflowIds.map((id) => ({ id, pass: true, fixture, groundingReview: { status: reviewStatus } }));
}

function canonicalJudgeProduct(overrides = {}) {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  return {
    runId: "product-run", completedAt: "2026-07-20T00:00:00Z", sourceRevision: "abc", scope: "all", fixture,
    environment: "local-synthetic", harness: "deepagents", model: "product-model",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: canonicalAtomicResults(fixture), workflows: canonicalWorkflowResults(fixture),
    ...overrides,
  };
}

function judgeRecord(product, verdict = "pass", judge = { kind: "human", reviewer: "Human Reviewer" }) {
  const rubric = loadMvpJudgeRubric();
  return {
    schemaVersion: 1,
    kind: "mvp-advisory-judge-record",
    productRunId: product.runId,
    sourceRevision: product.sourceRevision,
    fixtureVersion: product.fixture.fixtureVersion,
    fixtureHash: product.fixture.fixtureHash,
    skillSha256: product.skill.sha256,
    rubricVersion: rubric.version,
    judge,
    judgedAt: "2026-07-22T12:00:00Z",
    atomicJudgments: rubric.rubrics.flatMap(({ caseId, questions }) => questions.map(({ dimension, question }) => ({
      caseId, dimension, question, verdict, reason: "The recorded reply is adequately supported.",
    }))),
    workflowJudgments: rubric.workflows.flatMap(({ workflowId, questions }) => questions.map(({ dimension, question }) => ({
      workflowId, dimension, question, verdict, reason: "The recorded conversation is adequately supported.",
    }))),
  };
}

test("Waza accepts internally consistent declared and observed task counts", () => {
  const summary = summarizeWaza(wazaGate());
  assert.equal(summary.countsConsistent, true);
  assert.equal(summary.status, "RECORDED");
  assert.equal(summary.gatePass, true);
});

test("Waza rejects inconsistent declared counts and result collections", () => {
  for (const [label, report] of [
    ["total", wazaGate({ summary: { total_tests: 3, succeeded: 4, failed: 0, errors: 0, skipped: 0 } })],
    ["passed", wazaGate({ summary: { total_tests: 4, succeeded: 3, failed: 0, errors: 0, skipped: 0 } })],
    ["failed", wazaGate({ summary: { total_tests: 4, succeeded: 4, failed: 1, errors: 0, skipped: 0 } })],
    ["results", wazaGate({ tasks: WAZA_GATE_TASK_IDS.slice(0, -1).map((test_id) => ({ test_id, status: "passed" })) })],
  ]) {
    const summary = summarizeWaza(report);
    assert.equal(summary.countsConsistent, false, label);
    assert.equal(summary.status, "FAILED", label);
    assert.equal(summary.gatePass, false, label);
  }
});

test("Waza gate rejects advisory or duplicate five-task counterexamples", () => {
  const duplicate = wazaGate({
    summary: { total_tests: 5, succeeded: 5, failed: 0, errors: 0, skipped: 0 },
    tasks: [...WAZA_GATE_TASK_IDS, WAZA_GATE_TASK_IDS[0]].map((test_id) => ({ test_id, status: "passed" })),
    csaMvpProvenance: { ...wazaGate().csaMvpProvenance, tag: "advisory" },
  });
  assert.equal(summarizeWaza(duplicate).gatePass, false);
});

test("atomic case definitions name forbidden tools and bind rejection attempts to the intended target", () => {
  const suite = JSON.parse(readFileSync(new URL("./evals/mvp-cases.json", import.meta.url)));
  const workflows = JSON.parse(readFileSync(new URL("./evals/mvp-workflows.json", import.meta.url)));
  for (const item of suite.cases.filter((entry) => entry.id !== "MVP-E7-marker-prose-is-inert")) {
    assert.ok(item.expectation.forbiddenToolNames?.length > 0, `${item.id} must name forbidden tools`);
  }
  for (const id of ["MVP-E5-missing-reason", "MVP-E6-outsider-change"]) {
    const item = suite.cases.find((entry) => entry.id === id);
    assert.equal(item.expectation.argumentTargetId, "eng-product-launch");
    assert.equal(item.expectation.toolCall.name, "set_engagement_status");
    assert.equal(item.expectation.toolCall.args.engagement_id, "eng-product-launch");
  }
  assert.deepEqual(suite.cases.map((item) => item.id), MVP_EVAL_MANIFEST.atomicCaseIds);
  assert.deepEqual(workflows.workflows.map((item) => item.id), MVP_EVAL_MANIFEST.workflowIds);
  assert.deepEqual(
    suite.cases.find((item) => item.id === "MVP-E1-list-authorized").expectation.modelVisibleOutput,
    { kind: "authorizedEngagementList" },
  );
  assert.equal(suite.cases.find((item) => item.id === "MVP-E1-list-authorized").expectation.assistantResponseRequired, true);
  assert.deepEqual(
    suite.cases.find((item) => item.id === "MVP-E2-read-grounded").expectation.modelVisibleOutput,
    { kind: "engagementDetail", engagementId: "eng-product-launch" },
  );
  assert.equal(suite.cases.find((item) => item.id === "MVP-E2-read-grounded").expectation.assistantResponseRequired, true);
});

test("E1 and E2 require exact native model-visible renderings and a user-visible response", () => {
  const suite = JSON.parse(readFileSync(new URL("./evals/mvp-cases.json", import.meta.url)));
  const e1 = suite.cases.find((item) => item.id === "MVP-E1-list-authorized").expectation;
  const e2 = suite.cases.find((item) => item.id === "MVP-E2-read-grounded").expectation;
  const listState = {
    user: { id: "dan" },
    engagements: [
      {
        id: "eng-product-launch", name: "Product Launch", customer: "Fabrikam", status: "yellow", statusNote: "Awaiting sign-off", startDate: "2026-07-01", targetDate: "2026-08-28", description: "Launch plan",
        members: [{ userId: "ava", role: "owner" }, { userId: "dan", role: "editor" }],
        tasks: [{ id: "t-1", title: "Price review", status: "Done", priority: "High", dueDate: "2026-07-15" }, { id: "t-2", title: "Legal review", status: "To do", priority: "Medium", dueDate: "2026-07-20" }],
        actions: [], milestones: [], risks: [], library: [{ id: "doc-1" }, { id: "doc-2" }], conventions: [],
      },
      {
        id: "eng-q3-budget", name: "Q3 Budget", customer: "", status: "green", statusNote: "", startDate: "", targetDate: "", description: "",
        members: [{ userId: "dan", role: "owner" }], tasks: [], actions: [], milestones: [], risks: [], library: [], conventions: [],
      },
    ],
  };
  const listResult = { operation: "list", status: "succeeded", code: "engagement.listed" };
  const listEvents = [start(), ...tool({ id: "list-1", name: "list_engagements", args: {}, result: listResult }), ...text("I found two Engagements."), finish()];
  const validListOutput = [
    "2 engagement(s):",
    "- [eng-product-launch] Product Launch | your role: editor | customer=Fabrikam | status=yellow (Awaiting sign-off) | open tasks=1 | target=2026-08-28 | docs: 2",
    "- [eng-q3-budget] Q3 Budget | your role: owner | customer=n/a | status=green | open tasks=0 | target=n/a | docs: 0",
  ].join("\n");
  const validList = evaluateCase({
    expectation: e1, before: listState, after: listState, events: listEvents,
    rawRecords: [rawTool({ id: "list-1", name: "list_engagements", args: {}, output: validListOutput.replace(/\n/g, "\r\n"), result: listResult })],
  });
  assert.equal(validList.pass, true);
  assert.equal(validList.checks.authorizedEngagementIdsGrounded, true);

  for (const [label, output] of [
    ["name", validListOutput.replace("Product Launch", "Fabricated Launch")],
    ["customer", validListOutput.replace("customer=Fabrikam", "customer=Contoso")],
    ["status", validListOutput.replace("status=yellow (Awaiting sign-off)", "status=green")],
    ["status reason", validListOutput.replace("Awaiting sign-off", "Fabricated reason")],
    ["open task count", validListOutput.replace("open tasks=1", "open tasks=0")],
    ["target", validListOutput.replace("target=2026-08-28", "target=2099-01-01")],
    ["docs count", validListOutput.replace("docs: 2", "docs: 9")],
    ["actor role", validListOutput.replace("your role: editor", "your role: viewer")],
    ["count", validListOutput.replace("2 engagement(s):", "1 engagement(s):")],
    ["order", [validListOutput.split("\n")[0], ...validListOutput.split("\n").slice(1).reverse()].join("\n")],
  ]) {
    const fabricated = evaluateCase({
      expectation: e1, before: listState, after: listState, events: listEvents,
      rawRecords: [rawTool({ id: "list-1", name: "list_engagements", args: {}, result: listResult, output })],
    });
    assert.equal(fabricated.pass, false, label);
    assert.equal(fabricated.checks.authorizedEngagementIdsGrounded, false, label);
  }

  const emptyListResponse = evaluateCase({
    expectation: e1, before: listState, after: listState,
    events: [start(), ...tool({ id: "list-1", name: "list_engagements", args: {}, result: listResult }), finish()],
    rawRecords: [rawTool({ id: "list-1", name: "list_engagements", args: {}, result: listResult, output: validListOutput })],
  });
  assert.equal(emptyListResponse.pass, false);
  assert.equal(emptyListResponse.checks.assistantResponsePresent, false);

  const incompleteListState = structuredClone(listState);
  delete incompleteListState.user;
  const incompleteList = evaluateCase({
    expectation: e1, before: incompleteListState, after: incompleteListState, events: listEvents,
    rawRecords: [rawTool({ id: "list-1", name: "list_engagements", args: {}, result: listResult, output: validListOutput })],
  });
  assert.equal(incompleteList.pass, false);
  assert.equal(incompleteList.checks.authorizedEngagementIdsGrounded, false);

  const incompleteStatusState = structuredClone(listState);
  delete incompleteStatusState.engagements[0].status;
  const incompleteStatus = evaluateCase({
    expectation: e1, before: incompleteStatusState, after: incompleteStatusState, events: listEvents,
    rawRecords: [rawTool({ id: "list-1", name: "list_engagements", args: {}, result: listResult, output: validListOutput })],
  });
  assert.equal(incompleteStatus.pass, false);
  assert.equal(incompleteStatus.checks.authorizedEngagementIdsGrounded, false);

  const detailState = {
    user: { id: "ava" },
    engagements: [{
      id: "eng-product-launch", name: "Product Launch", customer: "Fabrikam", status: "yellow", statusNote: "Awaiting sign-off",
      startDate: "2026-07-01", targetDate: "2026-08-28", members: [{ userId: "ava", role: "owner" }, { userId: "dan", role: "editor" }], description: "V2 product rollout",
      tasks: [{ id: "t-1", title: "Finalize pricing tiers", status: "To do", priority: "High", dueDate: "2026-07-15" }],
      actions: [{ id: "a-1", title: "Confirm pricing", status: "Open", owner: "ava", dueDate: "2026-07-16" }],
      milestones: [{ id: "m-1", title: "Pricing approved", status: "Planned", dueDate: "2026-07-22" }],
      risks: [{ id: "r-1", title: "Pricing delay", severity: "High", status: "Open" }],
      library: [{ id: "doc-1" }, { id: "doc-2" }], conventions: [{ id: "c-1", text: "Use French." }],
    }],
  };
  const getResult = { operation: "get", status: "succeeded", code: "engagement.retrieved", resource: { kind: "engagement", id: "eng-product-launch" } };
  const getEvents = [start(), ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult }), ...text("Here is Product Launch."), finish()];
  const validDetailOutput = [
    "Engagement [eng-product-launch] Product Launch",
    "customer=Fabrikam | status=yellow (Awaiting sign-off) | start=2026-07-01 | target=2026-08-28",
    "members: ava(owner), dan(editor)",
    "description: V2 product rollout",
    "tasks:", "- [t-1] Finalize pricing tiers | To do | High | 2026-07-15",
    "actions:", "- [a-1] Confirm pricing | Open | ava | 2026-07-16",
    "milestones:", "- [m-1] Pricing approved | Planned | 2026-07-22",
    "risks:", "- [r-1] Pricing delay | High | Open",
    "artifacts: 2", "conventions: Use French.",
  ].join("\n");
  const validDetail = evaluateCase({
    expectation: e2, before: detailState, after: detailState, events: getEvents,
    rawRecords: [rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, output: validDetailOutput.replace(/\n/g, "\r\n"), result: getResult })],
  });
  assert.equal(validDetail.pass, true);
  assert.equal(validDetail.checks.engagementDetailFactsGrounded, true);

  for (const [label, output] of [
    ["heading", validDetailOutput.replace("Product Launch", "Fabricated Launch")],
    ["summary", validDetailOutput.replace("customer=Fabrikam", "customer=Contoso")],
    ["members", validDetailOutput.replace("ava(owner), dan(editor)", "ava(owner), sam(viewer)")],
    ["description", validDetailOutput.replace("V2 product rollout", "Fabricated description")],
    ["task row", validDetailOutput.replace("Finalize pricing tiers", "Fabricated task")],
    ["action row", validDetailOutput.replace("Confirm pricing", "Fabricated action")],
    ["milestone row", validDetailOutput.replace("Pricing approved", "Fabricated milestone")],
    ["risk row", validDetailOutput.replace("Pricing delay", "Fabricated risk")],
    ["artifacts", validDetailOutput.replace("artifacts: 2", "artifacts: 9")],
    ["conventions", validDetailOutput.replace("Use French.", "Invented convention.")],
  ]) {
    const fabricated = evaluateCase({
      expectation: e2, before: detailState, after: detailState, events: getEvents,
      rawRecords: [rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult, output })],
    });
    assert.equal(fabricated.pass, false, label);
    assert.equal(fabricated.checks.engagementDetailFactsGrounded, false, label);
  }

  const emptyDetailResponse = evaluateCase({
    expectation: e2, before: detailState, after: detailState,
    events: [start(), ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult }), finish()],
    rawRecords: [rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult, output: validDetailOutput })],
  });
  assert.equal(emptyDetailResponse.pass, false);
  assert.equal(emptyDetailResponse.checks.assistantResponsePresent, false);
});

test("wrong-target reads and missing model-visible output cannot pass", () => {
  const state = { engagements: [{ id: "eng-product-launch", status: "green", statusNote: "" }] };
  const expectation = {
    operation: "get",
    status: "succeeded",
    resourceId: "eng-product-launch",
    stateChanged: false,
    toolCall: { name: "get_engagement", args: { engagement_id: "eng-product-launch" } },
    completeToolEvidence: true,
  };
  const wrongResult = { operation: "get", status: "succeeded", code: "engagement.retrieved", resource: { kind: "engagement", id: "eng-wrong" } };
  const wrongEvents = [start(), ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-wrong" }, result: wrongResult }), finish()];
  const wrong = evaluateCase({
    expectation,
    before: state,
    after: state,
    events: wrongEvents,
    rawRecords: [rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-wrong" }, result: wrongResult })],
  });
  assert.equal(wrong.pass, false);
  assert.equal(wrong.checks.resourceMatchesTarget, false);
  assert.equal(wrong.checks.expectedToolCall, false);

  const rightResult = { operation: "get", status: "succeeded", code: "engagement.retrieved", resource: { kind: "engagement", id: "eng-product-launch" } };
  const rightEvents = [start(), ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: rightResult }), finish()];
  const missingOutput = evaluateCase({ expectation, before: state, after: state, events: rightEvents });
  assert.equal(missingOutput.pass, false);
  assert.equal(missingOutput.checks.completeModelVisibleToolEvidence, false);

  const complete = evaluateCase({
    expectation,
    before: state,
    after: state,
    events: rightEvents,
    rawRecords: [rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: rightResult })],
  });
  assert.equal(complete.pass, true);

  const mixedEvents = [
    start(),
    ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: rightResult }),
    ...tool({ id: "get-2", name: "get_engagement", args: { engagement_id: "eng-wrong" }, result: wrongResult }),
    finish(),
  ];
  const mixed = evaluateCase({
    expectation,
    before: state,
    after: state,
    events: mixedEvents,
    rawRecords: [
      rawTool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: rightResult }),
      rawTool({ id: "get-2", name: "get_engagement", args: { engagement_id: "eng-wrong" }, result: wrongResult }),
    ],
  });
  assert.equal(mixed.pass, false);
  assert.equal(mixed.checks.noUnexpectedResourceTargets, false);
  assert.equal(mixed.checks.noUnexpectedArgumentTargets, false);
});

test("the workflow fixture allows control-only exact navigation while requiring prose for the brief and mutation", () => {
  const workflow = JSON.parse(readFileSync(new URL("./evals/mvp-workflows.json", import.meta.url)))
    .workflows.find((item) => item.id === "MVP-W1-engagement-meeting-to-action");
  assert.ok(workflow);
  assert.equal(workflow.turns[0].expectation.assistantResponseRequired, true);
  assert.equal(workflow.turns[1].expectation.assistantResponseRequired, true);
  assert.equal(workflow.turns[2].expectation.assistantResponseRequired, false);

  const skill = { name: "engagement-meeting-prep", sha256: "abc123" };
  const initial = { engagements: [{ id: "eng-product-launch", name: "Product Launch", status: "green", statusNote: "", activity: [] }] };
  const updated = { engagements: [{ id: "eng-product-launch", name: "Product Launch", status: "yellow", statusNote: "Pricing approval slipped", activity: [{ ts: "volatile", userId: "dan", action: "engagement.updated", detail: "status, statusNote" }] }] };

  const listResult = { operation: "list", status: "succeeded", code: "engagement.listed" };
  const getResult = { operation: "get", status: "succeeded", code: "engagement.retrieved", resource: { kind: "engagement", id: "eng-product-launch" } };
  const updateResult = { operation: "update", status: "committed", code: "engagement.committed", resource: { kind: "engagement", id: "eng-product-launch" } };
  const destination = { id: "engagement_overview", path: "/engagements/eng-product-launch", engagementId: "eng-product-launch" };
  const navigateResult = { operation: "navigate", status: "resolved", code: "navigation.resolved", resource: { kind: "engagement", id: "eng-product-launch" }, destination };

  const turns = [
    {
      sessionId: "session-1", before: initial, after: initial,
      events: [start("run-1"), ...tool({ id: "list-1", name: "list_engagements", args: {}, result: listResult }), ...tool({ id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult }), ...text("Grounded brief"), finish("run-1")],
      rawRecords: [
        rawTool({ run: "run-1", id: "list-1", name: "list_engagements", args: {}, result: listResult }),
        rawTool({ run: "run-1", id: "get-1", name: "get_engagement", args: { engagement_id: "eng-product-launch" }, result: getResult }),
        { kind: "skill_invoked", run_id: "run-1", skill, model_visible_output: "skill body" },
      ],
    },
    {
      sessionId: "session-1", before: initial, after: updated,
      events: [start("run-2"), ...tool({ id: "update-1", name: "set_engagement_status", args: { engagement_id: "eng-product-launch", status: "yellow", note: "Pricing approval slipped" }, result: updateResult }), ...text("Updated", "message-2"), finish("run-2")],
      rawRecords: [rawTool({ run: "run-2", id: "update-1", name: "set_engagement_status", args: { engagement_id: "eng-product-launch", status: "yellow", note: "Pricing approval slipped" }, result: updateResult })],
    },
    {
      sessionId: "session-1", before: updated, after: updated,
      events: [start("run-3"), ...tool({ id: "nav-1", name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" }, result: navigateResult, navigation: { runId: "run-3", requestedAtNavigationVersion: 0, destination } }), finish("run-3")],
      rawRecords: [rawTool({ run: "run-3", id: "nav-1", name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" }, result: navigateResult })],
    },
  ];
  const definition = {
    groundingTurn: 0,
    turns: [
      { expectation: { operation: "get", status: "succeeded", resourceId: "eng-product-launch", stateChanged: false, requiredToolNames: ["list_engagements", "get_engagement"], forbiddenToolNames: ["set_engagement_status", "navigate"], toolCall: { name: "get_engagement", args: { engagement_id: "eng-product-launch" } }, completeToolEvidence: true, skill, assistantResponseRequired: true, noNavigation: true } },
      { expectation: { operation: "update", status: "committed", resourceId: "eng-product-launch", stateChanged: true, onlyEngagementMayChange: "eng-product-launch", exactEngagementUpdate: { id: "eng-product-launch", actor: "dan", detail: "status, statusNote" }, engagementAfter: { id: "eng-product-launch", status: "yellow", statusNote: "Pricing approval slipped" }, toolCall: { name: "set_engagement_status", args: { engagement_id: "eng-product-launch", status: "yellow", note: "Pricing approval slipped" } }, completeToolEvidence: true, assistantResponseRequired: true, forbiddenSkillNames: [skill.name] } },
      { expectation: { operation: "navigate", status: "resolved", resourceId: "eng-product-launch", stateChanged: false, toolCall: { name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" } }, completeToolEvidence: true, assistantResponseRequired: false, forbiddenSkillNames: [skill.name], navigation: { destination, requestedAtNavigationVersion: 0 } } },
    ],
    finalEngagement: { id: "eng-product-launch", status: "yellow", statusNote: "Pricing approval slipped" },
  };
  const passed = evaluateWorkflow({ definition, resetCount: 1, sessionId: "session-1", before: initial, turns, after: updated });
  assert.equal(passed.pass, true);
  assert.equal(passed.turnResults[2].assistantResponse, "");
  assert.equal(passed.turnResults[2].checks.assistantResponsePresent, true);
  assert.equal(passed.turnResults[2].checks.completeModelVisibleToolEvidence, true);
  assert.equal(passed.turnResults[2].checks.expectedNavigation, true);
  assert.equal(passed.groundingReview.status, "REVIEW_REQUIRED");

  const wrongSession = structuredClone(turns);
  wrongSession[2].sessionId = "session-2";
  const failed = evaluateWorkflow({ definition, resetCount: 1, sessionId: "session-1", before: initial, turns: wrongSession, after: updated });
  assert.equal(failed.pass, false);
  assert.equal(failed.checks.oneSession, false);
});

test("the scorecard keeps product and Waza provenance separate and never self-accepts a baseline", () => {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  const product = {
    runId: "product-run",
    completedAt: "2026-07-20T00:00:00Z",
    sourceRevision: "abc",
    fixture,
    environment: "local-synthetic",
    harness: "deepagents",
    model: "gpt-test",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: [{ id: "a", pass: true, fixture }],
    workflows: [{ id: "w", pass: true, fixture, groundingReview: { status: "REVIEW_REQUIRED" } }],
  };
  const waza = wazaGate();
  const scorecard = buildMvpScorecard(product, waza);
  assert.equal(scorecard.lanes.productRuntime.provenance, "deepagents/gpt-test");
  assert.equal(scorecard.lanes.productRuntime.fixtureConsistent, true);
  assert.equal(scorecard.lanes.productRuntime.groundingReviewBinding.status, "NOT_SUPPLIED");
  assert.equal(scorecard.lanes.skillLaboratory.provenance, "waza/copilot-sdk");
  assert.equal(scorecard.lanes.skillLaboratory.status, "RECORDED");
  assert.equal(scorecard.lanes.skillLaboratory.passed, 4);
  assert.equal(scorecard.lanes.skillLaboratory.total, 4);
  assert.equal(scorecard.lanes.skillLaboratory.gatePass, true);
  assert.equal(scorecard.lanes.skillLaboratory.skillNameMatchesProduct, true);
  assert.equal(scorecard.acceptance.baseline, "NOT_ACCEPTED");
  assert.equal(scorecard.acceptance.status, "INCOMPLETE");
});

test("only the exact all-scope canonical suite can pass the product hard gate", () => {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  const product = {
    runId: "product-run", completedAt: "2026-07-20T00:00:00Z", sourceRevision: "abc", scope: "all", fixture,
    environment: "local-synthetic", harness: "deepagents", model: "gpt-test",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: canonicalAtomicResults(fixture), workflows: canonicalWorkflowResults(fixture),
  };
  const full = buildMvpScorecard(product);
  assert.equal(full.lanes.productRuntime.fixtureConsistent, true);
  assert.equal(full.lanes.productRuntime.canonicalAtomicSuite, true);
  assert.equal(full.lanes.productRuntime.canonicalWorkflowSuite, true);
  assert.equal(full.lanes.productRuntime.hardGatePass, true);
  assert.equal(full.acceptance.status, "INCOMPLETE");

  const truthy = structuredClone(product);
  truthy.results[0].pass = "true";
  const truthyScorecard = buildMvpScorecard(truthy);
  assert.equal(truthyScorecard.lanes.productRuntime.atomic.passed, MVP_EVAL_MANIFEST.atomicCaseIds.length - 1);
  assert.equal(truthyScorecard.lanes.productRuntime.hardGatePass, false);

  const review = {
    productRunId: "product-run", sourceRevision: "abc", fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash",
    skillSha256: "hash", reviewer: "Human Reviewer", reviewedAt: "2026-07-20T01:00:00Z",
    reviews: [{ workflowId: "MVP-W1-engagement-meeting-to-action", status: "APPROVED" }],
  };

  for (const results of [
    product.results.slice(0, -1),
    [{ ...product.results[0], id: "MVP-E99-substituted" }, ...product.results.slice(1)],
    [...product.results.slice(0, -1), product.results[0]],
  ]) {
    const scorecard = buildMvpScorecard({ ...product, results }, wazaGate(), review);
    assert.equal(scorecard.lanes.productRuntime.hardGatePass, false);
    assert.equal(scorecard.acceptance.status, "INCOMPLETE");
  }
});

test("a workflow-only report remains evidence, not full readiness", () => {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  const product = {
    runId: "workflow-only-run",
    completedAt: "2026-07-20T00:00:00Z",
    sourceRevision: "abc",
    scope: "workflow",
    fixture,
    environment: "local-synthetic",
    harness: "deepagents",
    model: "gpt-test",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: [],
    workflows: canonicalWorkflowResults(fixture, "APPROVED"),
  };
  const scorecard = buildMvpScorecard(product, wazaGate());
  assert.equal(scorecard.lanes.productRuntime.workflows.passed, 1);
  assert.equal(scorecard.lanes.productRuntime.canonicalWorkflowSuite, true);
  assert.equal(scorecard.lanes.productRuntime.hardGatePass, false);
  assert.equal(scorecard.acceptance.status, "INCOMPLETE");
});

test("human review, fixture, Waza source, and skill identities must all match before a candidate is ready", () => {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  const product = {
    runId: "product-run",
    completedAt: "2026-07-20T00:00:00Z",
    sourceRevision: "abc",
    scope: "all",
    fixture,
    environment: "local-synthetic",
    harness: "deepagents",
    model: "gpt-test",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: canonicalAtomicResults(fixture),
    workflows: canonicalWorkflowResults(fixture),
  };
  const waza = wazaGate();
  const review = {
    productRunId: "product-run",
    sourceRevision: "abc",
    fixtureVersion: "mvp-demo-v2",
    fixtureHash: "fixture-hash",
    skillSha256: "hash",
    reviewer: "Human Reviewer",
    reviewedAt: "2026-07-20T01:00:00Z",
    reviews: [{ workflowId: "MVP-W1-engagement-meeting-to-action", status: "APPROVED", note: "Every claim matches tool output." }],
  };
  const ready = buildMvpScorecard(product, waza, review);
  assert.equal(ready.lanes.productRuntime.groundingReviewBinding.status, "MATCHED");
  assert.equal(ready.lanes.productRuntime.groundingReviews[0].status, "APPROVED");
  assert.equal(ready.acceptance.status, "READY_FOR_BASELINE");
  assert.equal(ready.acceptance.baseline, "NOT_ACCEPTED");

  const unrelatedWaza = buildMvpScorecard(product, { ...waza, skill: "some-other-skill" }, review);
  assert.equal(unrelatedWaza.lanes.skillLaboratory.skillNameMatchesProduct, false);
  assert.equal(unrelatedWaza.acceptance.status, "INCOMPLETE");

  const fakeWaza = buildMvpScorecard(product, {
    ...waza,
    config: { model_id: "fake", engine_type: "not-copilot" },
    summary: { total_tests: 1, failed: 0, errors: 0, skipped: 0 },
    tasks: [{ test_id: "unrelated", status: "passed" }],
  }, review);
  assert.equal(fakeWaza.lanes.skillLaboratory.gatePass, false);
  assert.equal(fakeWaza.acceptance.status, "INCOMPLETE");

  const wrongSkillHash = structuredClone(waza);
  wrongSkillHash.csaMvpProvenance.skill.sha256 = "wrong";
  const mismatchedSkill = buildMvpScorecard(product, wrongSkillHash, review);
  assert.equal(mismatchedSkill.lanes.skillLaboratory.skillNameMatchesProduct, false);
  assert.equal(mismatchedSkill.acceptance.status, "INCOMPLETE");

  const dirtyWaza = structuredClone(waza);
  dirtyWaza.csaMvpProvenance.sourceDirtyBefore = true;
  const mismatchedSource = buildMvpScorecard(product, dirtyWaza, review);
  assert.equal(mismatchedSource.lanes.skillLaboratory.sourceMatchesProduct, false);
  assert.equal(mismatchedSource.acceptance.status, "INCOMPLETE");

  const inconsistentProduct = structuredClone(product);
  inconsistentProduct.workflows[0].fixture = {
    ...inconsistentProduct.workflows[0].fixture,
    fixtureHash: "different-fixture",
  };
  const inconsistentFixture = buildMvpScorecard(inconsistentProduct, waza, review);
  assert.equal(inconsistentFixture.lanes.productRuntime.fixtureConsistent, false);
  assert.equal(inconsistentFixture.acceptance.status, "INCOMPLETE");

  const mismatched = buildMvpScorecard(product, waza, { ...review, skillSha256: "wrong" });
  assert.equal(mismatched.lanes.productRuntime.groundingReviewBinding.status, "MISMATCHED");
  assert.equal(mismatched.acceptance.status, "INCOMPLETE");
});

test("the advisory judge record binds the complete canonical atomic and workflow rubric", () => {
  const product = canonicalJudgeProduct();
  const record = judgeRecord(product);
  const validated = validateMvpJudgeRecord(record, product);
  assert.equal(validated.atomicJudgments.length, MVP_EVAL_MANIFEST.atomicCaseIds.length * 3);
  assert.equal(validated.workflowJudgments.length, MVP_EVAL_MANIFEST.workflowIds.length * 3);
  assert.deepEqual(validated.judge, { kind: "human", reviewer: "Human Reviewer" });
  assert.equal(validated.judgedAt, "2026-07-22T12:00:00Z");
  const summary = summarizeMvpJudge(record, product);
  assert.equal(summary.status, "RECORDED");
  assert.equal(summary.binding.status, "MATCHED");
  assert.deepEqual(summary.provenance, { rubricVersion: 1, judge: { kind: "human", reviewer: "Human Reviewer" }, judgedAt: "2026-07-22T12:00:00Z" });
  assert.equal(summary.atomic.passed, 27);
  assert.equal(summary.atomic.dimensions.accuracy.passed, 9);
  assert.equal(summary.workflows.passed, 3);
  assert.equal(summary.workflows.dimensions.tone.passed, 1);
  assert.deepEqual(summary.atomic.judgments[0], record.atomicJudgments[0]);
});

test("the advisory judge rejects missing, extra, duplicate, and mismatched-bound records", () => {
  const product = canonicalJudgeProduct();
  const complete = judgeRecord(product);
  const cases = [
    ["missing", { ...complete, atomicJudgments: complete.atomicJudgments.slice(1) }],
    ["extra", { ...complete, atomicJudgments: [...complete.atomicJudgments, complete.atomicJudgments[0]] }],
    ["duplicate", { ...complete, atomicJudgments: [...complete.atomicJudgments.slice(0, -1), complete.atomicJudgments[0]] }],
    ["unknown", { ...complete, atomicJudgments: [{ ...complete.atomicJudgments[0], caseId: "MVP-E99" }, ...complete.atomicJudgments.slice(1) ] }],
    ["binding", { ...complete, skillSha256: "wrong" }],
  ];
  for (const [label, record] of cases) {
    assert.throws(() => validateMvpJudgeRecord(record, product), Error, label);
  }
  const mismatch = summarizeMvpJudge(cases.at(-1)[1], product);
  assert.equal(mismatch.status, "INVALID");
  assert.equal(mismatch.binding.status, "MISMATCHED");
});

test("the advisory judge rejects malformed verdicts and reasons", () => {
  const product = canonicalJudgeProduct();
  const complete = judgeRecord(product);
  for (const [label, judgment] of [
    ["verdict", { ...complete.atomicJudgments[0], verdict: "approved" }],
    ["blank reason", { ...complete.atomicJudgments[0], reason: "" }],
    ["two sentences", { ...complete.atomicJudgments[0], reason: "It is grounded. It is useful." }],
    ["unterminated reason", { ...complete.atomicJudgments[0], reason: "It is grounded" }],
  ]) {
    const record = { ...complete, atomicJudgments: [judgment, ...complete.atomicJudgments.slice(1)] };
    assert.throws(() => validateMvpJudgeRecord(record, product), Error, label);
  }
});

test("the advisory judge enforces human or independent-model provenance and valid timestamps", () => {
  const product = canonicalJudgeProduct();
  const modelRecord = judgeRecord(product, "pass", { kind: "model", provider: " example ", model: " judge-model " });
  const humanRecord = judgeRecord(product, "pass", { kind: "human", reviewer: " Human Reviewer " });
  assert.equal(validateMvpJudgeRecord(modelRecord, product).judge.model, "judge-model");
  assert.equal(validateMvpJudgeRecord(modelRecord, product).judge.provider, "example");
  assert.equal(validateMvpJudgeRecord(humanRecord, product).judge.reviewer, "Human Reviewer");
  for (const [label, record] of [
    ["same model", judgeRecord(product, "pass", { kind: "model", provider: "example", model: "product-model" })],
    ["padded same model", judgeRecord(product, "pass", { kind: "model", provider: "example", model: " product-model " })],
    ["bad timestamp", { ...judgeRecord(product), judgedAt: "2026-07-22" }],
    ["extra judge field", judgeRecord(product, "pass", { kind: "human", reviewer: "Human Reviewer", provider: "example" })],
    ["extra record field", { ...judgeRecord(product), unexpected: true }],
    ["extra judgment field", { ...judgeRecord(product), atomicJudgments: [{ ...judgeRecord(product).atomicJudgments[0], unexpected: true }, ...judgeRecord(product).atomicJudgments.slice(1)] }],
  ]) {
    assert.throws(() => validateMvpJudgeRecord(record, product), Error, label);
  }
});

test("the advisory judge requires each exact dimension question and the canonical product suite", () => {
  const product = canonicalJudgeProduct();
  const complete = judgeRecord(product);
  const wrongDimension = {
    ...complete,
    atomicJudgments: [{ ...complete.atomicJudgments[0], dimension: "tone" }, ...complete.atomicJudgments.slice(1)],
  };
  assert.throws(() => validateMvpJudgeRecord(wrongDimension, product), Error);
  assert.throws(() => validateMvpJudgeRecord(complete, { ...product, results: product.results.slice(1) }), Error);
  assert.throws(() => validateMvpJudgeRecord(complete, { ...product, scope: "workflow" }), Error);
  const inconsistentFixture = structuredClone(product);
  inconsistentFixture.results[0] = {
    ...inconsistentFixture.results[0],
    fixture: { ...inconsistentFixture.fixture, fixtureHash: "inconsistent" },
  };
  assert.throws(() => validateMvpJudgeRecord(judgeRecord(inconsistentFixture), inconsistentFixture), Error);
  const rubric = loadMvpJudgeRubric();
  const extraEntryField = structuredClone(rubric);
  extraEntryField.rubrics[0].unexpected = true;
  const extraQuestionField = structuredClone(rubric);
  extraQuestionField.rubrics[0].questions[0].unexpected = true;
  const missingDimension = structuredClone(rubric);
  missingDimension.rubrics[0].questions.pop();
  for (const invalidRubric of [extraEntryField, extraQuestionField, missingDimension]) {
    assert.throws(() => validateMvpJudgeRubric(invalidRubric), Error);
  }
});

test("advisory judge verdicts never alter deterministic acceptance", () => {
  const fixture = { fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash" };
  const product = {
    runId: "product-run", completedAt: "2026-07-20T00:00:00Z", sourceRevision: "abc", scope: "all", fixture,
    environment: "local-synthetic", harness: "deepagents", model: "gpt-test",
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
    results: canonicalAtomicResults(fixture), workflows: canonicalWorkflowResults(fixture),
  };
  const review = {
    productRunId: "product-run", sourceRevision: "abc", fixtureVersion: "mvp-demo-v2", fixtureHash: "fixture-hash",
    skillSha256: "hash", reviewer: "Human Reviewer", reviewedAt: "2026-07-20T01:00:00Z",
    reviews: [{ workflowId: "MVP-W1-engagement-meeting-to-action", status: "APPROVED" }],
  };
  const passed = buildMvpScorecard(product, wazaGate(), review, judgeRecord(product, "pass"));
  const failed = buildMvpScorecard(product, wazaGate(), review, judgeRecord(product, "fail"));
  assert.equal(passed.lanes.advisoryJudge.status, "RECORDED");
  assert.equal(failed.lanes.advisoryJudge.atomic.failed, 27);
  assert.equal(passed.acceptance.status, "READY_FOR_BASELINE");
  assert.equal(failed.acceptance.status, "READY_FOR_BASELINE");
  assert.equal(passed.lanes.productRuntime.hardGatePass, failed.lanes.productRuntime.hardGatePass);
});

test("the scorecard preserves judge details and safely renders invalid judge diagnostics", () => {
  const product = canonicalJudgeProduct();
  const recorded = buildMvpScorecard(product, wazaGate(), null, judgeRecord(product));
  assert.equal(recorded.lanes.advisoryJudge.atomic.judgments.length, 27);
  assert.equal(recorded.lanes.advisoryJudge.workflows.judgments.length, 3);
  const paddedReason = judgeRecord(product);
  paddedReason.atomicJudgments[0].reason = "  The recorded reply is adequately supported.  ";
  assert.equal(validateMvpJudgeRecord(paddedReason, product).atomicJudgments[0].reason, "The recorded reply is adequately supported.");
  const invalid = buildMvpScorecard(product, wazaGate(), null, { ...judgeRecord(product), fixtureHash: "bad\r|hash" });
  const markdown = renderMvpScorecard(invalid);
  assert.equal(invalid.lanes.advisoryJudge.status, "INVALID");
  assert.match(markdown, /Advisory judge diagnostic/);
  assert.match(markdown, /bad \\\|hash/);
  assert.doesNotMatch(markdown, /\r/);
  const backslashPipe = buildMvpScorecard(product, wazaGate(), null, { ...judgeRecord(product), fixtureHash: "bad\\|hash" });
  const backslashPipeMarkdown = renderMvpScorecard(backslashPipe);
  const safelyEscaped = `bad${"\\".repeat(3)}|hash`;
  assert.equal(backslashPipeMarkdown.includes(safelyEscaped), true);
  assert.equal(backslashPipeMarkdown.includes("bad\\|hash"), false);
});

test("the scorecard merger keeps its three- and four-argument forms compatible", () => {
  const directory = mkdtempSync(join(tmpdir(), "csa-mvp-scorecard-"));
  try {
    const product = canonicalJudgeProduct();
    const review = {
      productRunId: product.runId, sourceRevision: product.sourceRevision,
      fixtureVersion: product.fixture.fixtureVersion, fixtureHash: product.fixture.fixtureHash, skillSha256: product.skill.sha256,
      reviewer: "Human Reviewer", reviewedAt: "2026-07-20T01:00:00Z",
      reviews: [{ workflowId: "MVP-W1-engagement-meeting-to-action", status: "APPROVED" }],
    };
    const productPath = join(directory, "product.json");
    const wazaPath = join(directory, "waza.json");
    const reviewPath = join(directory, "review.json");
    writeFileSync(productPath, JSON.stringify(product));
    writeFileSync(wazaPath, JSON.stringify(wazaGate()));
    writeFileSync(reviewPath, JSON.stringify(review));
    for (const [prefix, args] of [
      [join(directory, "three"), [productPath, wazaPath, join(directory, "three")]],
      [join(directory, "four"), [productPath, wazaPath, join(directory, "four"), reviewPath]],
    ]) {
      execFileSync(process.execPath, ["scripts/mvp_scorecard_merge.mjs", ...args], { cwd: process.cwd(), stdio: "pipe" });
      assert.equal(JSON.parse(readFileSync(`${prefix}.json`, "utf8")).lanes.advisoryJudge.status, "NOT_SUPPLIED");
    }
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});
