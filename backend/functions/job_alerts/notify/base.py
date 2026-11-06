"""What the pipeline needs in order to alert."""
from collections.abc import Callable

from ..models import Company, Job, JobScore


class NotifyError(RuntimeError):
    """The alert was not delivered, so the job must retry next poll."""


# A score of None means scoring failed: the alert still goes out, marked "not scored".
Notifier = Callable[[Company, Job, JobScore | None], None]
