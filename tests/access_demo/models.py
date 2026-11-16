from django.db import models

from core.access.models import BaseModel


class Note(BaseModel):
    title = models.CharField(max_length=100)
