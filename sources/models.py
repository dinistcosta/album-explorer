from django.db import models


class HttpCacheEntry(models.Model):
    key = models.CharField(max_length=64, unique=True)
    status = models.IntegerField()
    body = models.BinaryField()
    fetched_at = models.DateTimeField()


class SourceThrottle(models.Model):
    source = models.CharField(max_length=32, unique=True)
    next_allowed_at = models.DateTimeField()
    last_foreground_at = models.DateTimeField(null=True, blank=True)
