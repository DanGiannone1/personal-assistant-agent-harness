import { parseEngagementRoute } from "./engagementRoute";

function expect(condition: boolean, message: string): void {
  if (!condition) throw new Error(message);
}

function expectRoute(
  viewRoute: string,
  expected: { id: string; sub: string; recordId: string },
): void {
  const actual = parseEngagementRoute(viewRoute);
  expect(
    actual !== null &&
      actual.id === expected.id &&
      actual.sub === expected.sub &&
      actual.recordId === expected.recordId,
    `${viewRoute} must parse to ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`,
  );
}

function expectInvalidRoute(viewRoute: string): void {
  expect(
    parseEngagementRoute(viewRoute) === null,
    `${viewRoute} must be rejected as an invalid Engagement route`,
  );
}

expectRoute("/engagements/eng-1", {
  id: "eng-1",
  sub: "",
  recordId: "",
});
expectRoute("/engagements/eng-1/tasks", {
  id: "eng-1",
  sub: "tasks",
  recordId: "",
});
expectRoute("/engagements/eng-1/documents", {
  id: "eng-1",
  sub: "documents",
  recordId: "",
});
expectRoute("/engagements/eng-1/settings", {
  id: "eng-1",
  sub: "settings",
  recordId: "",
});
expectRoute("/engagements/eng-1/tasks/task-1", {
  id: "eng-1",
  sub: "tasks",
  recordId: "task-1",
});

expectInvalidRoute("/engagements");
expectInvalidRoute("/engagements//tasks");
expectInvalidRoute("/engagements/eng-1/unknown");
expectInvalidRoute("/engagements/eng-1/tasks/task-1/extra");
expectInvalidRoute("/engagements/eng-1/documents/doc-1");
expectInvalidRoute("/engagements/eng-1/settings/member-1");
expectInvalidRoute("/engagements/eng 1");
expectInvalidRoute("/engagements/eng-1/tasks/task.1");
expectInvalidRoute("/engagements/eng-1/");
expectInvalidRoute("engagements/eng-1");
