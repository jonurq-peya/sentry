import logging
import operator
from enum import StrEnum
from typing import Any

from django.db import models

from sentry.backup.scopes import RelocationScope
from sentry.db.models import DefaultFieldsModel, region_silo_model, sane_repr
from sentry.workflow_engine.types import DataConditionResult, DetectorPriorityLevel

logger = logging.getLogger(__name__)


def get_nested_value(data: Any, path: str, default: Any = None) -> Any | None:
    try:
        value = data
        for part in path.split("."):
            if hasattr(value, part):
                value = getattr(value, part)
            elif hasattr(value, "get"):
                value = value.get(part)
            else:
                return default
        return value
    except Exception:
        return default


class Condition(StrEnum):
    EQUAL = "eq"
    GREATER_OR_EQUAL = "gte"
    GREATER = "gt"
    LESS_OR_EQUAL = "lte"
    LESS = "lt"
    NOT_EQUAL = "ne"
    EVENT_COMPARISON = "event_comparison"


condition_ops = {
    Condition.EQUAL: operator.eq,
    Condition.GREATER_OR_EQUAL: operator.ge,
    Condition.GREATER: operator.gt,
    Condition.LESS_OR_EQUAL: operator.le,
    Condition.LESS: operator.lt,
    Condition.NOT_EQUAL: operator.ne,
    Condition.EVENT_COMPARISON: operator.eq,
}


FILTER_VALUE_BY_CONDITIONS = {Condition.EVENT_COMPARISON}


@region_silo_model
class DataCondition(DefaultFieldsModel):
    """
    A data condition is a way to specify a logic condition, if the condition is met, the condition_result is returned.
    """

    __relocation_scope__ = RelocationScope.Organization
    __repr__ = sane_repr("type", "condition")

    # The condition is the logic condition that needs to be met, gt, lt, eq, etc.
    condition = models.CharField(max_length=200)

    # The comparison is the value that the condition is compared to for the evaluation, this must be a primitive value
    comparison = models.JSONField()

    # The condition_result is the value that is returned if the condition is met, this must be a primitive value
    condition_result = models.JSONField()

    # The type of condition, this is used to initialize the condition classes
    type = models.CharField(max_length=200)

    condition_group = models.ForeignKey(
        "workflow_engine.DataConditionGroup",
        related_name="conditions",
        on_delete=models.CASCADE,
    )

    def get_condition_result(self) -> DataConditionResult:
        match self.condition_result:
            case float() | bool():
                return self.condition_result
            case int() | DetectorPriorityLevel():
                try:
                    return DetectorPriorityLevel(self.condition_result)
                except ValueError:
                    return self.condition_result
            case _:
                logger.error(
                    "Invalid condition result",
                    extra={"condition_result": self.condition_result, "id": self.id},
                )

        return None

    def evaluate_value(self, value: Any) -> DataConditionResult:
        # TODO: This logic should be in a condition class that we get from `self.type`
        # TODO: This evaluation logic should probably go into the condition class, and we just produce a condition
        # class from this model
        try:
            condition_op_key = Condition(self.type)
        except ValueError:
            logger.exception(
                "Invalid condition", extra={"condition": self.condition, "id": self.id}
            )
            return None

        op = condition_ops.get(condition_op_key)
        if op is None:
            logger.error("Invalid condition", extra={"condition": self.condition, "id": self.id})
            return None

        if self.type in FILTER_VALUE_BY_CONDITIONS:
            value = get_nested_value(value, self.condition)

        if op(value, self.comparison):
            return self.get_condition_result()

        return None
