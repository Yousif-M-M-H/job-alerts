"""Send job alerts through the Telegram Bot API."""
import requests

from ..models import Company, Job, JobScore
from .base import NotifyError

API_URL = "https://api.telegram.org/bot{token}/sendMessage"
TIMEOUT_SECONDS = 20


def format_alert(company: Company, job: Job, score: JobScore | None) -> str:
    heading = f"{job.title} · {score.score}%" if score else f"{job.title} · not scored"
    place = f"{company.name} · {'; '.join(job.locations)}"
    lines = (heading, place, score.reason, job.url) if score else (heading, place, job.url)
    return "\n".join(lines)


class TelegramNotifier:
    def __init__(self, token: str, chat_id: str) -> None:
        if not token or not chat_id:
            raise ValueError("Telegram token and chat ID are required")
        self._token = token
        self._chat_id = chat_id

    def __call__(self, company: Company, job: Job, score: JobScore | None) -> None:
        body = {"chat_id": self._chat_id, "text": format_alert(company, job, score)}
        try:
            response = requests.post(API_URL.format(token=self._token), json=body, timeout=TIMEOUT_SECONDS)
        except requests.RequestException as error:
            # Request errors can quote the URL, which contains the token. Keep only the type.
            raise NotifyError(f"Telegram request failed: {type(error).__name__}") from None
        if response.status_code != 200:
            raise NotifyError(f"Telegram returned HTTP {response.status_code}")
