"""The one model-visible MVP tool schema catalog, shared by both adapters."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


DestinationId = Literal[
    "engagements", "engagement_overview", "engagement_tasks", "engagement_artifacts",
]


class NavigateCommand(BaseModel):
    destination_id: DestinationId = Field(description="CSA Workbench catalog destination ID.")
    engagement_id: str | None = Field(default=None, description="Required for engagement destinations.")


class ListEngagementsCommand(BaseModel):
    pass


class CreateEngagementCommand(BaseModel):
    name: str = Field(description="Engagement name.")
    description: str = Field(default="", description="Optional engagement description.")
    customer: str = Field(default="", description="Optional customer name.")
    target_date: str = Field(default="", description="Optional target date in YYYY-MM-DD form.")


class GetEngagementCommand(BaseModel):
    engagement_id: str = Field(description="Stable Engagement ID.")


class UpdateEngagementCommand(GetEngagementCommand):
    name: str | None = Field(default=None)
    description: str | None = Field(default=None)
    customer: str | None = Field(default=None)
    start_date: str | None = Field(default=None)
    target_date: str | None = Field(default=None)


class SetEngagementStatusCommand(GetEngagementCommand):
    status: str = Field(description="green, yellow, or red")
    note: str = Field(default="", description="Required reason for yellow or red.")


class ShareEngagementCommand(GetEngagementCommand):
    user: str = Field(description="User ID to share with.")
    role: str = Field(default="viewer", description="viewer, editor, or owner")


ACTIVE_TOOL_SCHEMAS = {
    "navigate": NavigateCommand,
    "list_engagements": ListEngagementsCommand,
    "create_engagement": CreateEngagementCommand,
    "get_engagement": GetEngagementCommand,
    "update_engagement": UpdateEngagementCommand,
    "set_engagement_status": SetEngagementStatusCommand,
    "share_engagement": ShareEngagementCommand,
}
