"""What the pipeline needs in order to alert."""
from collections.abc import Callable

from ..models import Company, Job


class NotifyError(RuntimeError):
    """The alert was not delivered, so the job must retry next poll."""


Notifier = Callable[[Company, Job], None]
