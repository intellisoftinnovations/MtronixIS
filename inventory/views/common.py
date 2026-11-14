import csv
import datetime

from django.core.paginator import Paginator
from django.http import HttpResponse

from inventory.timeutils import bd_day_start


def paginate(request, qs, per_page=20):
    paginator = Paginator(qs, per_page)
    return paginator.get_page(request.GET.get("page"))


def csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("\ufeff")  # BOM so Excel opens UTF-8 correctly
    writer = csv.writer(response)
    writer.writerow(header)
    for row in rows:
        writer.writerow([_safe_cell(v) for v in row])
    return response


def _safe_cell(value):
    """Prevent CSV/formula injection in spreadsheet apps."""
    if value is None:
        return ""
    s = str(value)
    if s and s[0] in "=+-@\t\r":
        return "'" + s
    return s


def date_range_filter(qs, field, date_from, date_to):
    if date_from:
        qs = qs.filter(**{f"{field}__gte": bd_day_start(date_from)})
    if date_to:
        qs = qs.filter(**{f"{field}__lt": bd_day_start(date_to + datetime.timedelta(days=1))})
    return qs


def safe_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default

