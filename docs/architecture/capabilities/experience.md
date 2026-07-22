# Experience

## Main pages

CSA Workbench opens on Home. The main navigation contains:

- **Home**, including the user's Engagement portfolio and personal agenda
- **Engagements**
- **My work:** Tasks, Calendar, and Reminders
- **AI Mode**, the dedicated assistant workspace
- **Settings**

Opening an Engagement shows Overview, Tasks, Artifacts, and Team & conventions. The header shows the
Engagement status and the current user's role.

## Manual and assistant actions

Every supported product action has a normal web interface. The assistant provides another way to
perform selected actions and navigation.

Manual navigation happens immediately in the browser. Assistant navigation happens only after the
`navigate` tool returns a valid destination for the current user. Route-like text in a message does
not move the application.

The assistant can navigate to eight destinations:

| Destination | Path |
|---|---|
| Engagement list | `/engagements` |
| Engagement overview | `/engagements/{engagement_id}` |
| Engagement tasks | `/engagements/{engagement_id}/tasks` |
| Engagement artifacts | `/engagements/{engagement_id}/artifacts` |
| Home | `/home` |
| Tasks | `/todo` |
| Calendar | `/calendar` |
| Reminders | `/reminders` |

AI Mode and Settings are available through normal application controls but are not assistant
navigation destinations.

## Roles in the interface

| Role | Available controls |
|---|---|
| Owner | Edit all Engagement information and manage members |
| Editor | Edit delivery information, tasks, conventions, and artifacts |
| Viewer | Read the Engagement and download artifacts |

Hiding or disabling a control helps the user understand their role. The server still checks every
request.

## Assistant presentations

The assistant appears as a dock beside the application and as a larger `/assistant` page. Both use
the same session and conversation. Moving between them keeps messages and current application data.

Tool progress and completion appear inline with the conversation. After an assistant tool finishes,
the application reloads the relevant records. If that refresh fails, the last successful data stays
visible with a retry option.

## Responsive behavior

| Width | Behavior |
|---|---|
| 1200px and wider | Persistent navigation and assistant dock |
| 768px to 1199px | Navigation drawer and assistant overlay |
| 767px and narrower | Single-column content with the same drawer and overlay behavior |

The navigation drawer traps keyboard focus, closes with Escape or a backdrop click, and returns
focus to its opener. Forms and controls remain usable at a 390 CSS-pixel viewport.

## Common states

Pages include loading, empty, validation, not-found, read-only, save-in-progress, and retry states.
Validation messages are associated with their fields. Navigation controls use semantic buttons,
active items use `aria-current`, and keyboard focus remains visible.
