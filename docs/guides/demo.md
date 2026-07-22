# Demo guide

This demo shows the main shared-work and assistant workflow.

## Before the demo

1. Start an isolated local application using the [local development guide](local-development.md).
2. Confirm that the demo user can sign in and open Engagements.
3. Reset only the isolated demo data when a clean starting point is required.

## Main workflow

1. Create or open the **Product Launch** Engagement in the web application.
2. Ask the assistant to prepare for the Product Launch status meeting.
3. Confirm that the meeting brief uses the Engagement's recorded customer, status, dates,
   milestones, tasks, and risks.
4. Tell the assistant:

   ```text
   Pricing approval slipped. Set its status to Yellow with the exact reason
   'Pricing approval slipped'.
   ```

5. Confirm that Product Launch now shows Yellow with that exact reason.
6. Tell the assistant: `Open it.`
7. Confirm that the application opens the Product Launch Engagement.

## Private-work workflow

1. Ask the assistant to create a private task.
2. Open Tasks and confirm that the new task belongs to the signed-in user.
3. Ask the assistant to open Reminders.
4. Confirm that the application moves to Reminders without changing another user's records.

## What the demo explains

- The web application works without the assistant.
- Shared Engagements and private work have different ownership rules.
- The assistant uses typed tools for supported actions.
- The application reloads saved records after assistant activity.
- Assistant text that resembles a route or successful action has no effect by itself.

The versioned automated cases are stored in `tests/evals/mvp-cases.json` and
`tests/evals/mvp-workflows.json`.
