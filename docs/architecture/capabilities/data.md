# Data

CSA Workbench stores shared customer work, private personal work, durable Engagement artifacts, and
temporary assistant files. These categories have different owners and lifetimes.

## Engagements

An Engagement is one shared customer record. It includes:

- name, description, customer, status, status reason, and dates;
- members and their roles;
- Engagement tasks;
- working conventions;
- artifact metadata; and
- activity entries.

An owner can manage all fields and members. An editor can change delivery information, tasks,
conventions, and artifacts. A viewer can read the record and download artifacts.

The API and assistant share `EngagementService` for creating, listing, reading, updating, setting
status, and sharing Engagements. Some actions remain web-only: renaming, member removal, Engagement
tasks, conventions, and artifacts.

Yellow and Red status values require a reason. The final owner cannot be removed or demoted. There
is no Engagement delete or archive action.

## Private work

Each user has one private Cosmos record identified by `personal-{uid}`. It contains Tasks with
subtasks, Calendar events, and Reminders. These records never belong to an Engagement and cannot be
shared with another user.

The API and assistant share `PersonalWorkspaceService` for all private-work operations. The server
derives the owner from the authenticated user rather than a request field.

## Engagement artifacts

Artifact metadata is stored with the Engagement. File bytes use the configured artifact backend:

- `.mvp-artifacts/<run-id>/` during isolated local development;
- Azure Blob Storage when configured for an Entra deployment.

Members can list and download artifacts. Owners and editors can upload and remove them. Uploads must
be non-empty and no larger than 20 MiB.

The assistant does not currently read or manage Engagement artifacts.

## Assistant files

Session uploads and generated files live in the temporary assistant workspace. Uploads accept
Markdown files only. These files are separate from Engagement artifacts and disappear when the
runtime workspace is replaced.

## Sessions

The API and runtime keep session ownership in process memory. A session belongs to one authenticated
user and cannot be rebound. Replacing the API or runtime process ends existing sessions but does not
affect Engagements or private work.

Only one assistant turn may run in a session at a time. A second concurrent turn receives
`409 Session is busy`. Stopping a browser stream does not undo a tool action that already saved.

## Concurrent updates

Engagement and private-work updates use Cosmos ETags. On a conflict, the service reloads the newest
record, rechecks permissions, reapplies the requested change, and retries a limited number of times.

Artifact bytes and Engagement metadata cannot be saved in one Cosmos transaction. Upload writes the
bytes first and removes them if metadata cannot be saved. Delete removes metadata first and then the
bytes.
