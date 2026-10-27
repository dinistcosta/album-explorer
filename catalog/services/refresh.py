from datetime import timedelta

from django.utils import timezone

STALE_AFTER = timedelta(days=30)


def needs_enrichment(obj) -> bool:
    return obj.enriched_at is None or timezone.now() - obj.enriched_at > STALE_AFTER


def enqueue_enrichment(obj) -> None:
    """Enqueue the enrichment task for an Album or Artist unless one is already queued/running."""
    from catalog import tasks
    from catalog.models import Album

    task = tasks.enrich_album if isinstance(obj, Album) else tasks.enrich_artist
    if _already_pending(task, obj.pk):
        return
    task.enqueue(obj.pk)


def _already_pending(task, object_id) -> bool:
    # Only the database backend leaves rows behind to look at; the immediate backend runs inline.
    from django.tasks.base import TaskResultStatus
    from django_tasks_db.models import DBTaskResult

    return DBTaskResult.objects.filter(
        task_path=task.module_path,
        args_kwargs={"args": [object_id], "kwargs": {}},
        status__in=[TaskResultStatus.READY, TaskResultStatus.RUNNING],
    ).exists()
