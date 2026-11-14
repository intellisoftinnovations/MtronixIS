"""Bangladesh-time helpers. Everything is stored in UTC and shown in Asia/Dhaka."""
import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.utils import timezone

DHAKA = ZoneInfo("Asia/Dhaka")
TZ_SUFFIX = "(BST, UTC+6)"


def to_bd(dt):
    if dt is None:
        return None
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, datetime.timezone.utc)
    return dt.astimezone(DHAKA)


def format_bd(dt, with_tz=True):
    """e.g. '12 Nov 2026, 03:45 PM (BST, UTC+6)'"""
    if dt is None:
        return ""
    s = to_bd(dt).strftime("%d %b %Y, %I:%M %p")
    return f"{s} {TZ_SUFFIX}" if with_tz else s


def bd_now():
    return timezone.now().astimezone(DHAKA)


def bd_day_start(date):
    return datetime.datetime.combine(date, datetime.time.min, tzinfo=DHAKA)


def period_ranges():
    """(start, end) aware datetimes for today / this week / this month in Dhaka time."""
    now = bd_now()
    today = now.date()
    week_start = today - datetime.timedelta(days=(today.weekday() - settings.MTX_WEEK_START) % 7)
    month_start = today.replace(day=1)
    end = now + datetime.timedelta(seconds=1)
    return {
        "today": (bd_day_start(today), end),
        "week": (bd_day_start(week_start), end),
        "month": (bd_day_start(month_start), end),
    }


def parse_date(value):
    try:
        return datetime.date.fromisoformat(value) if value else None
    except ValueError:
        return None

