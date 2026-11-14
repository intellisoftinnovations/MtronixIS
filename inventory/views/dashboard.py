import datetime

from django.contrib.auth.decorators import login_required
from django.db.models import Count, F, Q, Sum
from django.db.models.functions import Coalesce, TruncDate
from django.http import JsonResponse
from django.shortcuts import render

from inventory.models import UNITS, Carton, Product, StockMovement
from inventory.permissions import allowed_inventories
from inventory.timeutils import DHAKA, bd_day_start, bd_now, period_ranges

ALIVE = Q(cartons__is_deleted=False, cartons__product__is_deleted=False)


def summary_data(user):
    invs = allowed_inventories(user, include_archived=False)
    inv_ids = list(invs.values_list("id", flat=True))
    cartons = Carton.objects.filter(is_deleted=False, product__is_deleted=False, inventory_id__in=inv_ids)
    totals = cartons.aggregate(cartons=Coalesce(Sum("carton_count"), 0), units=Coalesce(Sum(UNITS), 0), lines=Count("id"))

    inventory_rows = invs.annotate(
        total_cartons=Coalesce(Sum("cartons__carton_count", filter=ALIVE), 0),
        total_units=Coalesce(Sum(F("cartons__carton_count") * F("cartons__qty_per_carton"), filter=ALIVE), 0),
        carton_lines=Count("cartons", filter=ALIVE),
        low_count=Count("cartons", filter=ALIVE & Q(cartons__carton_count__lt=F("low_stock_threshold"))),
    ).order_by("name")

    moves = StockMovement.objects.filter(inventory_id__in=inv_ids)
    periods = {}
    for key, (start, end) in period_ranges().items():
        agg = moves.filter(created_at__gte=start, created_at__lt=end).aggregate(
            in_cartons=Coalesce(Sum("cartons_moved", filter=Q(type="IN")), 0),
            in_units=Coalesce(Sum("qty_moved", filter=Q(type="IN")), 0),
            in_count=Count("id", filter=Q(type="IN")),
            out_cartons=Coalesce(Sum("cartons_moved", filter=Q(type="OUT")), 0),
            out_units=Coalesce(Sum("qty_moved", filter=Q(type="OUT")), 0),
            out_count=Count("id", filter=Q(type="OUT")),
        )
        periods[key] = agg

    low_stock = (
        cartons.filter(carton_count__lt=F("inventory__low_stock_threshold"))
        .exclude(status=Carton.Status.CLOSED)
        .select_related("product", "inventory")
        .order_by("carton_count", "product__name")
    )

    return {
        "inventory_ids": inv_ids,
        "total_inventories": len(inv_ids),
        "total_products": Product.objects.alive().count(),
        "total_cartons": totals["cartons"],
        "total_units": totals["units"],
        "carton_lines": totals["lines"],
        "inventory_rows": inventory_rows,
        "periods": periods,
        "low_stock": low_stock,
        "moves": moves,
    }


def build_chart(inv_ids, days):
    today = bd_now().date()
    start = today - datetime.timedelta(days=days - 1)
    rows = (
        StockMovement.objects.filter(inventory_id__in=inv_ids, created_at__gte=bd_day_start(start))
        .annotate(d=TruncDate("created_at", tzinfo=DHAKA))
        .values("d", "type")
        .annotate(c=Sum("cartons_moved"))
    )
    data = {}
    for r in rows:
        data.setdefault(r["d"], {"IN": 0, "OUT": 0})[r["type"]] = r["c"] or 0

    W, H, PL, PR, PT, PB = 720, 240, 44, 12, 14, 30
    plot_w, plot_h = W - PL - PR, H - PT - PB
    series = []
    for i in range(days):
        d = start + datetime.timedelta(days=i)
        v = data.get(d, {"IN": 0, "OUT": 0})
        series.append((d, v["IN"], v["OUT"]))
    max_v = max([max(s[1], s[2]) for s in series] + [1])
    # round axis max up to a "nice" number
    magnitude = 10 ** (len(str(int(max_v))) - 1)
    axis_max = ((max_v + magnitude - 1) // magnitude) * magnitude or 1

    group = plot_w / days
    bar = max(min(group * 0.34, 22), 2)
    label_every = 1 if days <= 7 else 5
    bars = []
    for i, (d, vin, vout) in enumerate(series):
        gx = PL + i * group + group / 2
        h_in = plot_h * vin / axis_max
        h_out = plot_h * vout / axis_max
        bars.append(
            {
                "date": d,
                "in": vin,
                "out": vout,
                "x_in": round(gx - bar - 1, 2),
                "x_out": round(gx + 1, 2),
                "y_in": round(PT + plot_h - h_in, 2),
                "y_out": round(PT + plot_h - h_out, 2),
                "h_in": round(h_in, 2),
                "h_out": round(h_out, 2),
                "w": round(bar, 2),
                "label_x": round(gx, 2),
                "label": d.strftime("%d %b") if (i % label_every == 0 or i == days - 1) else "",
            }
        )
    ticks = []
    for frac in (0, 0.25, 0.5, 0.75, 1):
        val = axis_max * frac
        ticks.append({"y": round(PT + plot_h - plot_h * frac, 2), "label": f"{val:,.0f}"})
    return {
        "W": W, "H": H, "PL": PL, "plot_right": W - PR, "base_y": PT + plot_h, "label_y": H - 10,
        "bars": bars, "ticks": ticks, "days": days,
        "total_in": sum(s[1] for s in series), "total_out": sum(s[2] for s in series),
    }


@login_required
def dashboard(request):
    data = summary_data(request.user)
    days = 30 if request.GET.get("range") == "30" else 7
    ctx = {
        **data,
        "recent": data["moves"].select_related("product", "inventory", "carton")[:10],
        "low_stock": data["low_stock"][:10],
        "low_stock_total": data["low_stock"].count(),
        "chart": build_chart(data["inventory_ids"], days),
    }
    return render(request, "inventory/dashboard.html", ctx)


@login_required
def dashboard_summary_api(request):
    data = summary_data(request.user)
    return JsonResponse(
        {
            "total_inventories": data["total_inventories"],
            "total_products": data["total_products"],
            "total_cartons": data["total_cartons"],
            "total_units": data["total_units"],
            "inventories": [
                {"id": i.id, "name": i.name, "code": i.code, "cartons": i.total_cartons, "units": i.total_units}
                for i in data["inventory_rows"]
            ],
            "periods": data["periods"],
            "low_stock_count": data["low_stock"].count(),
        }
    )

