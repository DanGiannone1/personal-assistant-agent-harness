"""Shared, dependency-light application rules for CSA Workbench."""

from .engagements import EngagementService, Outcome
from .tool_protocol import DESTINATION_IDS, ProductToolResult, validate_destination

__all__ = ["DESTINATION_IDS", "EngagementService", "Outcome", "ProductToolResult", "validate_destination"]
