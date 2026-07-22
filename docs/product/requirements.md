# MVP requirements

## Goal

A Cloud Solution Architect can manage private work, collaborate on a shared customer Engagement, and
use the assistant to perform supported actions through the same rules as the web application.

## Required behavior

1. The application provides Engagements, Home, Tasks, Calendar, Reminders, Assistant, and Settings.
2. A signed-in user can create an Engagement and becomes its owner.
3. Engagement members see the same shared record according to owner, editor, and viewer permissions.
4. Each user's Tasks, Calendar events, and Reminders remain private to that user.
5. The web application provides a manual path for every supported operation.
6. The assistant uses typed tools and structured results. Assistant text alone cannot change records
   or move the application to another page.
7. Engagement artifacts remain separate from temporary assistant-session files.
8. Session uploads accept Markdown files only.
9. The product includes the `engagement-meeting-prep`, `tasks`, `calendar`, and `weekly-review` skills.
10. Azure deployment uses an explicit instance name and model configuration. Deployment changes need
    a current plan and the user's approval.
11. Reminder email recipients come from the owning user's authenticated identity, and a failed send
    is recorded on the Reminder.

## Main user journeys

### Personal and shared work

Two users sign in and see only their own private work. They see only Engagements where they are
members. One user shares an Engagement with the other, and both then see the same shared record. A
non-member cannot read it.

### Assistant control

The assistant opens an authorized Engagement and makes a supported change through a typed tool. Text
that merely looks like a route, tool call, or success message has no application effect.

### Responsive use

The main journeys remain usable on wide, compact, and narrow screens. Loading, empty, validation,
permission, and failure states remain understandable.

### Isolated Azure deployment

An approved revision can deploy to its own Azure resource group using an explicit instance name and
model configuration. The deployment process checks the selected target before making changes.

## Exclusions

The MVP does not include global Library or Search pages, general document retrieval, non-Markdown
session uploads, unattended assistant-generated Reminder content, or a Copilot production runtime.
It does not promise production readiness, external distribution, or accessibility certification.
