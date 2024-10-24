from sentry_relay.consts import SPAN_STATUS_CODE_TO_NAME
from snuba_sdk import AliasedExpression, Column, Function

from sentry.exceptions import InvalidSearchQuery
from sentry.search.events import constants
from sentry.search.events.builder.base import BaseQueryBuilder
from sentry.search.events.builder.discover import TimeseriesQueryBuilder, TopEventsQueryBuilder
from sentry.search.events.datasets.spans_indexed import (
    SpansEAPDatasetConfig,
    SpansIndexedDatasetConfig,
)
from sentry.search.events.fields import custom_time_processor
from sentry.search.events.types import SelectType

SPAN_UUID_FIELDS = {
    "trace",
    "trace_id",
    "transaction.id",
    "transaction_id",
    "profile.id",
    "profile_id",
    "replay.id",
    "replay_id",
}


SPAN_ID_FIELDS = {
    "id",
    "span_id",
    "parent_span",
    "parent_span_id",
    "segment.id",
    "segment_id",
}


class SpansIndexedQueryBuilderMixin:
    meta_resolver_map: dict[str, str]

    def get_field_type(self, field: str) -> str | None:
        if field in self.meta_resolver_map:
            return self.meta_resolver_map[field]
        if field in ["span.duration", "span.self_time"]:
            return "duration"

        return None


class SpansIndexedQueryBuilder(SpansIndexedQueryBuilderMixin, BaseQueryBuilder):
    requires_organization_condition = False
    uuid_fields = SPAN_UUID_FIELDS
    span_id_fields = SPAN_ID_FIELDS
    config_class = SpansIndexedDatasetConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value_resolver_map[
            constants.SPAN_STATUS
        ] = lambda status: SPAN_STATUS_CODE_TO_NAME.get(status)


class SpansEAPQueryBuilder(SpansIndexedQueryBuilderMixin, BaseQueryBuilder):
    requires_organization_condition = True
    uuid_fields = SPAN_UUID_FIELDS
    span_id_fields = SPAN_ID_FIELDS
    config_class = SpansEAPDatasetConfig

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def resolve_field(self, raw_field: str, alias: bool = False) -> Column:
        # try the typed regex first
        if len(raw_field) <= 200:
            tag_match = constants.TYPED_TAG_KEY_RE.search(raw_field)
        else:
            raise InvalidSearchQuery(f"{raw_field} is too long, can be a maximum of 200 characters")
        field = tag_match.group("tag") if tag_match else None
        field_type = tag_match.group("type") if tag_match else None
        if (
            field is None
            or field_type is None
            or not constants.VALID_FIELD_PATTERN.match(field)
            # attr field is less permissive than tags, we can't have - in them
            or "-" in field
        ):
            # Temporary until at least after 22 Dec 2024 when old data rotates out, otherwise we should just call super
            # here and return default_field without any extra work
            default_field = super().resolve_field(raw_field, alias)
            if (
                isinstance(default_field, Column)
                and default_field.subscriptable == "attr_str"
                or isinstance(default_field, AliasedExpression)
                and default_field.exp.subscriptable == "attr_str"
            ):
                key = (
                    default_field.key
                    if isinstance(default_field, Column)
                    else default_field.exp.key
                )
                unprefixed_field = Column(f"attr_str[{key}]")
                prefixed_field = Column(f"attr_str[sentry.{key}]")
                return Function(
                    "if",
                    [
                        Function("mapContains", [Column("attr_str"), key]),
                        unprefixed_field,
                        prefixed_field,
                    ],
                    raw_field if alias else None,
                )
            else:
                return default_field

        if field_type not in ["number", "string"]:
            raise InvalidSearchQuery(
                f"Unknown type for field {raw_field}, only string and number are supported"
            )

        if field_type == "string":
            attr_type = "attr_str"
            field_col = Column(f"attr_str[{field}]")
        else:
            attr_type = "attr_num"
            field_col = Column(f"attr_num[{field}]")

        if alias:
            field_alias = f"tags_{field}@{field_type}"
            self.typed_tag_to_alias_map[raw_field] = field_alias
            self.alias_to_typed_tag_map[field_alias] = raw_field
        else:
            field_alias = None

        # Temporary until at least after 22 Dec 2024 when old data rotates out
        unprefixed_field = field_col
        prefixed_field = Column(f"{attr_type}[sentry.{field}]")
        col = Function(
            "if",
            [
                Function("mapContains", [Column(attr_type), field]),
                unprefixed_field,
                prefixed_field,
            ],
            field_alias,
        )

        return col


class TimeseriesSpanIndexedQueryBuilder(SpansIndexedQueryBuilderMixin, TimeseriesQueryBuilder):
    config_class = SpansIndexedDatasetConfig
    uuid_fields = SPAN_UUID_FIELDS
    span_id_fields = SPAN_ID_FIELDS

    @property
    def time_column(self) -> SelectType:
        return custom_time_processor(
            self.interval, Function("toUInt32", [Column("start_timestamp")])
        )


class TimeseriesSpanEAPIndexedQueryBuilder(SpansEAPQueryBuilder, TimeseriesQueryBuilder):
    pass


class TopEventsSpanIndexedQueryBuilder(SpansIndexedQueryBuilderMixin, TopEventsQueryBuilder):
    config_class = SpansIndexedDatasetConfig
    uuid_fields = SPAN_UUID_FIELDS
    span_id_fields = SPAN_ID_FIELDS

    @property
    def time_column(self) -> SelectType:
        return custom_time_processor(
            self.interval, Function("toUInt32", [Column("start_timestamp")])
        )


class TopEventsSpanEAPQueryBuilder(SpansEAPQueryBuilder, TopEventsQueryBuilder):
    pass
