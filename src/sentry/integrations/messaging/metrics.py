from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any

from sentry.integrations.utils.metrics import EventLifecycleMetric
from sentry.models.organization import Organization
from sentry.organizations.services.organization import RpcOrganization
from sentry.users.models import User
from sentry.users.services.user import RpcUser


class MessagingInteractionType(Enum):
    """A way in which a user can interact with Sentry through a messaging app."""

    # General interactions
    HELP = "HELP"
    LINK_IDENTITY = "LINK_IDENTITY"
    UNLINK_IDENTITY = "UNLINK_IDENTITY"
    LINK_TEAM = "LINK_TEAM"
    UNLINK_TEAM = "UNLINK_TEAM"

    # Interactions on Issues
    STATUS = "STATUS"
    ARCHIVE_DIALOG = "ARCHIVE_DIALOG"
    ARCHIVE = "ARCHIVE"
    ASSIGN_DIALOG = "ASSIGN_DIALOG"
    ASSIGN = "ASSIGN"
    UNASSIGN = "ASSIGN"
    RESOLVE_DIALOG = "RESOLVE_DIALOG"
    RESOLVE = "RESOLVE"
    UNRESOLVE = "UNRESOLVE"
    IGNORE = "IGNORE"
    MARK_ONGOING = "MARK_ONGOING"


@dataclass
class MessagingInteractionEvent(EventLifecycleMetric):
    """An instance to be recorded of a user interacting through a messaging app."""

    interaction_type: MessagingInteractionType
    provider: str

    # We can cram various optional attributes here if we want to capture them in logs
    user: User | RpcUser | None = None
    organization: Organization | RpcOrganization | None = None

    def get_key(self, outcome: str) -> str:
        tag_tokens = ["sentry", "integrations", "messaging", "slo"] + [
            self.provider,
            str(self.interaction_type).lower(),
            outcome,
        ]
        return ".".join(tag_tokens)

    def get_extras(self) -> Mapping[str, Any]:
        return {
            "interaction_type": self.interaction_type.value,
            "provider": self.provider,
            "user_id": (self.user.id if self.user else None),
            "organization_id": (self.organization.id if self.organization else None),
        }
