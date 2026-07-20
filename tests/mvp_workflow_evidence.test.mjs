import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { evaluateCase, evaluateWorkflow } from "../scripts/mvp_evidence.mjs";
import { buildMvpScorecard, WAZA_GATE_TASK_IDS } from "../scripts/mvp_scorecard.mjs";

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
  summary: { total_tests: 4, failed: 0, errors: 0, skipped: 0 },
  tasks: WAZA_GATE_TASK_IDS.map((test_id) => ({ test_id, status: "passed" })),
  csaMvpProvenance: {
    runner: "scripts/waza_eval.sh",
    wazaVersion: "0.38.3",
    sourceRevision: "abc",
    sourceRevisionAfter: "abc",
    sourceDirtyBefore: false,
    sourceDirtyAfter: false,
    skill: { name: "engagement-meeting-prep", sha256: "hash" },
  },
  ...overrides,
});

test("atomic case definitions name forbidden tools and bind rejection attempts to the intended target", () => {
  const suite = JSON.parse(readFileSync(new URL("./evals/mvp-cases.json", import.meta.url)));
  for (const item of suite.cases.filter((entry) => entry.id !== "MVP-E7-marker-prose-is-inert")) {
    assert.ok(item.expectation.forbiddenToolNames?.length > 0, `${item.id} must name forbidden tools`);
  }
  for (const id of ["MVP-E5-missing-reason", "MVP-E6-outsider-change"]) {
    const item = suite.cases.find((entry) => entry.id === id);
    assert.equal(item.expectation.argumentTargetId, "eng-product-launch");
    assert.equal(item.expectation.toolCall.name, "set_engagement_status");
    assert.equal(item.expectation.toolCall.args.engagement_id, "eng-product-launch");
  }
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

test("the three-turn workflow requires one session, one reset, skill identity, exact mutation, and exact navigation", () => {
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
      events: [start("run-3"), ...tool({ id: "nav-1", name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" }, result: navigateResult, navigation: { runId: "run-3", requestedAtNavigationVersion: 0, destination } }), ...text("Opened", "message-3"), finish("run-3")],
      rawRecords: [rawTool({ run: "run-3", id: "nav-1", name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" }, result: navigateResult })],
    },
  ];
  const definition = {
    groundingTurn: 0,
    turns: [
      { expectation: { operation: "get", status: "succeeded", resourceId: "eng-product-launch", stateChanged: false, requiredToolNames: ["list_engagements", "get_engagement"], forbiddenToolNames: ["set_engagement_status", "navigate"], toolCall: { name: "get_engagement", args: { engagement_id: "eng-product-launch" } }, completeToolEvidence: true, skill, assistantResponseRequired: true, noNavigation: true } },
      { expectation: { operation: "update", status: "committed", resourceId: "eng-product-launch", stateChanged: true, onlyEngagementMayChange: "eng-product-launch", exactEngagementUpdate: { id: "eng-product-launch", actor: "dan", detail: "status, statusNote" }, engagementAfter: { id: "eng-product-launch", status: "yellow", statusNote: "Pricing approval slipped" }, toolCall: { name: "set_engagement_status", args: { engagement_id: "eng-product-launch", status: "yellow", note: "Pricing approval slipped" } }, completeToolEvidence: true, forbiddenSkillNames: [skill.name] } },
      { expectation: { operation: "navigate", status: "resolved", resourceId: "eng-product-launch", stateChanged: false, toolCall: { name: "navigate", args: { destination_id: "engagement_overview", engagement_id: "eng-product-launch" } }, completeToolEvidence: true, forbiddenSkillNames: [skill.name], navigation: { destination, requestedAtNavigationVersion: 0 } } },
    ],
    finalEngagement: { id: "eng-product-launch", status: "yellow", statusNote: "Pricing approval slipped" },
  };
  const passed = evaluateWorkflow({ definition, resetCount: 1, sessionId: "session-1", before: initial, turns, after: updated });
  assert.equal(passed.pass, true);
  assert.equal(passed.groundingReview.status, "REVIEW_REQUIRED");

  const wrongSession = structuredClone(turns);
  wrongSession[2].sessionId = "session-2";
  const failed = evaluateWorkflow({ definition, resetCount: 1, sessionId: "session-1", before: initial, turns: wrongSession, after: updated });
  assert.equal(failed.pass, false);
  assert.equal(failed.checks.oneSession, false);
});

test("the scorecard keeps product and Waza provenance separate and never self-accepts a baseline", () => {
  const fixture = { fixtureVersion: "mvp-demo-v1", fixtureHash: "fixture-hash" };
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

test("human review, fixture, Waza source, and skill identities must all match before a candidate is ready", () => {
  const fixture = { fixtureVersion: "mvp-demo-v1", fixtureHash: "fixture-hash" };
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
  const review = {
    productRunId: "product-run",
    sourceRevision: "abc",
    fixtureVersion: "mvp-demo-v1",
    fixtureHash: "fixture-hash",
    skillSha256: "hash",
    reviewer: "Human Reviewer",
    reviewedAt: "2026-07-20T01:00:00Z",
    reviews: [{ workflowId: "w", status: "APPROVED", note: "Every claim matches tool output." }],
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
