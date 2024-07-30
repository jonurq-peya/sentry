from __future__ import annotations

import os
import time
from datetime import timedelta
from multiprocessing import JoinableQueue as Queue
from multiprocessing import Process
from typing import Final, Literal, TypeAlias
from uuid import uuid4

import click
import sentry_sdk
from django.conf import settings
from django.utils import timezone

from sentry.runner.decorators import log_options
from sentry.silo.base import SiloLimit, SiloMode


def get_project(value: str) -> int | None:
    from sentry.models.project import Project

    try:
        if value.isdigit():
            return int(value)
        if "/" not in value:
            return None
        org, proj = value.split("/", 1)
        return Project.objects.get(organization__slug=org, slug=proj).id
    except Project.DoesNotExist:
        return None


# We need a unique value to indicate when to stop multiprocessing queue
# an identity on an object() isn't guaranteed to work between parent
# and child proc
_STOP_WORKER: Final = "91650ec271ae4b3e8a67cdc909d80f8c"
_WorkQueue: TypeAlias = (
    "Queue[Literal['91650ec271ae4b3e8a67cdc909d80f8c'] | tuple[str, tuple[int, ...]]]"
)

API_TOKEN_TTL_IN_DAYS = 30


def debug_output(msg: str) -> None:
    if os.environ.get("SENTRY_CLEANUP_SILENT", None):
        return
    click.echo(msg)


def multiprocess_worker(task_queue: _WorkQueue) -> None:
    # Configure within each Process
    import logging

    from sentry.utils.imports import import_string

    logger = logging.getLogger("sentry.cleanup")

    from sentry.runner import configure

    configure()

    from sentry import deletions, models, similarity

    skip_models = [
        # Handled by other parts of cleanup
        models.EventAttachment,
        models.UserReport,
        models.Group,
        models.GroupEmailThread,
        models.GroupRuleStatus,
        # Handled by TTL
        similarity,
    ]

    while True:
        j = task_queue.get()
        if j == _STOP_WORKER:
            task_queue.task_done()

            return

        model_name, chunk = j
        model = import_string(model_name)
        try:
            task = deletions.get(
                model=model,
                query={"id__in": chunk},
                skip_models=skip_models,
                transaction_id=uuid4().hex,
            )

            while True:
                if not task.chunk():
                    break
        except Exception as e:
            logger.exception(e)
        finally:
            task_queue.task_done()


@click.command()
@click.option("--days", default=30, show_default=True, help="Numbers of days to truncate on.")
@click.option("--project", help="Limit truncation to only entries from project.")
@click.option(
    "--concurrency",
    type=int,
    default=1,
    show_default=True,
    help="The total number of concurrent worker processes to run.",
)
@click.option(
    "--silent", "-q", default=False, is_flag=True, help="Run quietly. No output on success."
)
@click.option("--model", "-m", multiple=True)
@click.option("--router", "-r", default=None, help="Database router")
@click.option(
    "--timed",
    "-t",
    default=False,
    is_flag=True,
    help="Send the duration of this command to internal metrics.",
)
@log_options()
def cleanup(
    days: int,
    project: str | None,
    concurrency: int,
    silent: bool,
    model: tuple[str, ...],
    router: str | None,
    timed: bool,
) -> None:
    """Delete a portion of trailing data based on creation date.

    All data that is older than `--days` will be deleted.  The default for
    this is 30 days.  In the default setting all projects will be truncated
    but if you have a specific project you want to limit this to this can be
    done with the `--project` flag which accepts a project ID or a string
    with the form `org/project` where both are slugs.
    """
    if concurrency < 1:
        click.echo("Error: Minimum concurrency is 1", err=True)
        raise click.Abort()

    os.environ["_SENTRY_CLEANUP"] = "1"
    if silent:
        os.environ["SENTRY_CLEANUP_SILENT"] = "1"

    # Make sure we fork off multiprocessing pool
    # before we import or configure the app

    pool = []
    task_queue: _WorkQueue = Queue(1000)
    for _ in range(concurrency):
        p = Process(target=multiprocess_worker, args=(task_queue,))
        p.daemon = True
        p.start()
        pool.append(p)

    try:
        from sentry.runner import configure

        configure()

        from django.apps import apps
        from django.db import router as db_router
        from django.db.models import Model

        from sentry import models, nodestore
        from sentry.constants import ObjectStatus
        from sentry.data_export.models import ExportedData
        from sentry.db.deletion import BulkDeleteQuery
        from sentry.models.notificationmessage import NotificationMessage
        from sentry.models.rulefirehistory import RuleFireHistory
        from sentry.monitors import models as monitor_models
        from sentry.replays import models as replay_models
        from sentry.utils import metrics
        from sentry.utils.query import RangeQuerySetWrapper

        start_time = None
        if timed:
            start_time = time.time()
        transaction = sentry_sdk.start_transaction(op="cleanup", name="cleanup")
        transaction.__enter__()
        transaction.set_tag("router", router)
        transaction.set_tag("model", model)

        # list of models which this query is restricted to
        model_list = {m.lower() for m in model}

        def is_filtered(model: type[Model]) -> bool:
            silo_limit = getattr(model._meta, "silo_limit", None)
            if isinstance(silo_limit, SiloLimit) and not silo_limit.is_available():
                return True
            if router is not None and db_router.db_for_write(model) != router:
                return True
            if not model_list:
                return False
            return model.__name__.lower() not in model_list

        # Deletions that use `BulkDeleteQuery` (and don't need to worry about child relations)
        # (model, datetime_field, order_by)
        additional_bulk_query_deletes = []
        for entry in settings.ADDITIONAL_BULK_QUERY_DELETES:
            app_name, model_name = entry[0].split(".")
            model_tp = apps.get_model(app_name, model_name)
            additional_bulk_query_deletes.append((model_tp, entry[1], entry[2]))

        BULK_QUERY_DELETES = [
            (models.UserReport, "date_added", None),
            (models.GroupEmailThread, "date", None),
            (RuleFireHistory, "date_added", None),
            (NotificationMessage, "date_added", None),
        ] + additional_bulk_query_deletes

        # Deletions that use the `deletions` code path (which handles their child relations)
        # (model, datetime_field, order_by)
        DELETES = [
            (models.EventAttachment, "date_added", "date_added"),
            (replay_models.ReplayRecordingSegment, "date_added", "date_added"),
            (models.ArtifactBundle, "date_added", "date_added"),
            (monitor_models.MonitorCheckIn, "date_added", "date_added"),
            (models.GroupRuleStatus, "date_added", "date_added"),
        ]
        # Deletions that we run per project. In some cases we can't use an index on just the date
        # column, so as an alternative we use `(project_id, <date_col>)` instead
        DELETES_BY_PROJECT = [
            # Having an index on `last_seen` sometimes caused the planner to make a bad plan that
            # used this index instead of a more appropriate one. This was causing a lot of postgres
            # load, so we had to remove it.
            (models.Group, "last_seen", "last_seen"),
            (models.ProjectDebugFile, "date_accessed", "date_accessed"),
        ]

        debug_output("Removing expired values for LostPasswordHash")
        if is_filtered(models.LostPasswordHash):
            debug_output(">> Skipping LostPasswordHash")
        else:
            models.LostPasswordHash.objects.filter(
                date_added__lte=timezone.now() - timedelta(hours=48)
            ).delete()

        debug_output("Removing expired values for OrganizationMember")
        if is_filtered(models.OrganizationMember):
            debug_output(">> Skipping OrganizationMember")
        else:
            expired_threshold = timezone.now() - timedelta(days=days)
            models.OrganizationMember.objects.delete_expired(expired_threshold)

        for model_tp in (models.ApiGrant, models.ApiToken):
            debug_output(f"Removing expired values for {model_tp.__name__}")

            if is_filtered(model_tp):
                debug_output(f">> Skipping {model_tp.__name__}")
            else:
                queryset = model_tp.objects.filter(
                    expires_at__lt=(timezone.now() - timedelta(days=API_TOKEN_TTL_IN_DAYS))
                )

                # SentryAppInstallations are associated to ApiTokens. We're okay
                # with these tokens sticking around so that the Integration can
                # refresh them, but all other non-associated tokens should be
                # deleted.
                if model_tp is models.ApiToken:
                    queryset = queryset.filter(sentry_app_installation__isnull=True)

                queryset.delete()

        if not silent:
            click.echo("Removing expired files associated with ExportedData")

        if is_filtered(ExportedData):
            debug_output(">> Skipping ExportedData files")
        else:
            export_data_queryset = ExportedData.objects.filter(date_expired__lt=(timezone.now()))
            for item in export_data_queryset:
                item.delete_file()

        project_id = None
        if SiloMode.get_current_mode() != SiloMode.CONTROL:
            if project:
                click.echo("Bulk NodeStore deletion not available for project selection", err=True)
                project_id = get_project(project)
                # These models span across projects, so let's skip them
                DELETES.remove((models.ArtifactBundle, "date_added", "date_added"))
                if project_id is None:
                    click.echo("Error: Project not found", err=True)
                    raise click.Abort()
            else:
                debug_output("Removing old NodeStore values")

                cutoff = timezone.now() - timedelta(days=days)
                try:
                    nodestore.backend.cleanup(cutoff)
                except NotImplementedError:
                    click.echo("NodeStore backend does not support cleanup operation", err=True)

        debug_output("Running bulk query deletes in BULK_QUERY_DELETES")
        for model_tp, dtfield, order_by in BULK_QUERY_DELETES:
            chunk_size = 10000

            debug_output(f"Removing {model_tp.__name__} for days={days} project={project or '*'}")
            if is_filtered(model_tp):
                debug_output(">> Skipping %s" % model_tp.__name__)
            else:
                BulkDeleteQuery(
                    model=model_tp,
                    dtfield=dtfield,
                    days=days,
                    project_id=project_id,
                    order_by=order_by,
                ).execute(chunk_size=chunk_size)

        debug_output("Running bulk deletes in DELETES")
        for model_tp, dtfield, order_by in DELETES:
            debug_output(f"Removing {model_tp.__name__} for days={days} project={project or '*'}")

            if is_filtered(model_tp):
                debug_output(">> Skipping %s" % model_tp.__name__)
            else:
                imp = ".".join((model_tp.__module__, model_tp.__name__))

                q = BulkDeleteQuery(
                    model=model_tp,
                    dtfield=dtfield,
                    days=days,
                    project_id=project_id,
                    order_by=order_by,
                )

                for chunk in q.iterator(chunk_size=100):
                    task_queue.put((imp, chunk))

                task_queue.join()

        project_deletion_query = None
        to_delete_by_project = []
        if SiloMode.get_current_mode() != SiloMode.CONTROL:
            debug_output("Preparing DELETES_BY_PROJECT context")
            project_deletion_query = models.Project.objects.filter(status=ObjectStatus.ACTIVE)
            if project:
                project_deletion_query = models.Project.objects.filter(id=project_id)

            for model_tp_tup in DELETES_BY_PROJECT:
                if is_filtered(model_tp_tup[0]):
                    debug_output(">> Skipping %s" % model_tp_tup[0].__name__)
                else:
                    to_delete_by_project.append(model_tp_tup)

        if project_deletion_query is not None and len(to_delete_by_project):
            debug_output("Running bulk deletes in DELETES_BY_PROJECT")
            for project_id_for_deletion in RangeQuerySetWrapper(
                project_deletion_query.values_list("id", flat=True),
                result_value_getter=lambda item: item,
            ):
                for model_tp, dtfield, order_by in to_delete_by_project:
                    debug_output(
                        f"Removing {model_tp.__name__} for days={days} project={project_id_for_deletion}"
                    )

                    imp = ".".join((model_tp.__module__, model_tp.__name__))

                    q = BulkDeleteQuery(
                        model=model_tp,
                        dtfield=dtfield,
                        days=days,
                        project_id=project_id_for_deletion,
                        order_by=order_by,
                    )

                    for chunk in q.iterator(chunk_size=100):
                        task_queue.put((imp, chunk))

        task_queue.join()

        # Clean up FileBlob instances which are no longer used and aren't super
        # recent (as there could be a race between blob creation and reference)
        debug_output("Cleaning up unused FileBlob references")
        if is_filtered(models.FileBlob):
            debug_output(">> Skipping FileBlob")
        else:
            cleanup_unused_files(silent)
    finally:
        # Shut down our pool
        for _ in pool:
            task_queue.put(_STOP_WORKER)

        # And wait for it to drain
        for p in pool:
            p.join()

    if timed and start_time:
        duration = int(time.time() - start_time)
        metrics.timing("cleanup.duration", duration, instance=router, sample_rate=1.0)
        click.echo("Clean up took %s second(s)." % duration)

    if transaction:
        transaction.__exit__(None, None, None)


def cleanup_unused_files(quiet: bool = False) -> None:
    """
    Remove FileBlob's (and thus the actual files) if they are no longer
    referenced by any File.

    We set a minimum-age on the query to ensure that we don't try to remove
    any blobs which are brand new and potentially in the process of being
    referenced.
    """
    from sentry.models.files.file import File
    from sentry.models.files.fileblob import FileBlob
    from sentry.models.files.fileblobindex import FileBlobIndex

    if quiet:
        from sentry.utils.query import RangeQuerySetWrapper
    else:
        from sentry.utils.query import RangeQuerySetWrapperWithProgressBar as RangeQuerySetWrapper

    cutoff = timezone.now() - timedelta(days=1)
    queryset = FileBlob.objects.filter(timestamp__lte=cutoff)

    for blob in RangeQuerySetWrapper(queryset):
        if FileBlobIndex.objects.filter(blob=blob).exists():
            continue
        if File.objects.filter(blob=blob).exists():
            continue
        blob.delete()
