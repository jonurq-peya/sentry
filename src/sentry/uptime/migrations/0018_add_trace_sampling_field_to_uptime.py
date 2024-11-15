# Generated by Django 5.1.1 on 2024-11-14 16:44

from django.db import migrations, models

from sentry.new_migrations.migrations import CheckedMigration


class Migration(CheckedMigration):
    # This flag is used to mark that a migration shouldn't be automatically run in production.
    # This should only be used for operations where it's safe to run the migration after your
    # code has deployed. So this should not be used for most operations that alter the schema
    # of a table.
    # Here are some things that make sense to mark as post deployment:
    # - Large data migrations. Typically we want these to be run manually so that they can be
    #   monitored and not block the deploy for a long period of time while they run.
    # - Adding indexes to large tables. Since this can take a long time, we'd generally prefer to
    #   run this outside deployments so that we don't block them. Note that while adding an index
    #   is a schema change, it's completely safe to run the operation after the code has deployed.
    # Once deployed, run these manually via: https://develop.sentry.dev/database-migrations/#migration-deployment

    is_post_deployment = False

    dependencies = [
        ("uptime", "0017_unique_on_timeout"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    """
                    ALTER TABLE "uptime_uptimesubscription" ADD COLUMN "trace_sampling" boolean NOT NULL DEFAULT false;
                    """,
                    reverse_sql="""
                    ALTER TABLE "uptime_uptimesubscription" DROP COLUMN "trace_sampling";
                    """,
                    hints={"tables": ["uptime_uptimesubscription"]},
                ),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="uptimesubscription",
                    name="trace_sampling",
                    field=models.BooleanField(default=False),
                ),
            ],
        )
    ]
