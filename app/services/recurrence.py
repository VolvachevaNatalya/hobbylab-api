from datetime import datetime, timedelta
from typing import List, Optional

from dateutil.relativedelta import relativedelta

from app.schemas.event_series import RecurrenceCreate


def generate_dates(recurrence: RecurrenceCreate, first_start: datetime) -> List[datetime]:
    """Return all occurrence datetimes for the series, including first_start."""
    cutoff = first_start + relativedelta(months=12) if recurrence.end_type == "never" else None

    def _step(dt: datetime) -> datetime:
        if recurrence.frequency == "daily":
            return dt + timedelta(days=recurrence.interval)
        if recurrence.frequency == "weekly":
            return dt + timedelta(weeks=recurrence.interval)
        if recurrence.frequency == "monthly":
            return dt + relativedelta(months=recurrence.interval)
        if recurrence.frequency == "yearly":
            return dt + relativedelta(years=recurrence.interval)
        raise ValueError(f"Unknown frequency: {recurrence.frequency!r}")

    dates: List[datetime] = [first_start]
    current = first_start

    while True:
        current = _step(current)

        if recurrence.end_type == "count":
            if len(dates) >= recurrence.total_count:
                break
        elif recurrence.end_type == "date":
            if current.date() > recurrence.end_date:
                break
        else:  # never
            if current > cutoff:
                break

        dates.append(current)

    return dates


def adjust_original_series_after_split(
    series,
    from_index: int,
    last_remaining_start: Optional[datetime],
) -> None:
    """Update the original series metadata to reflect that it now ends just before from_index.

    Does nothing when from_index == 0 (no events remain in the original series;
    the caller is responsible for deleting the series row in that case).
    """
    if from_index == 0:
        return

    if series.end_type == "count":
        series.total_count = from_index
    elif series.end_type == "date":
        if last_remaining_start is not None:
            series.end_date = last_remaining_start.date()
    elif series.end_type == "never":
        if last_remaining_start is not None:
            series.generated_until = last_remaining_start
