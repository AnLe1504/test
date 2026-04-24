from __future__ import annotations
from django import template

register = template.Library()


@register.filter
def star_rating(value):
    if value is None:
        return "—"
    try:
        filled = int(value)
        filled = max(1, min(5, filled))
        return "★" * filled + "☆" * (5 - filled)
    except (TypeError, ValueError):
        return "—"


@register.filter
def star_color_class(value):
    mapping = {1: "star-1", 2: "star-2", 3: "star-3", 4: "star-4", 5: "star-5"}
    try:
        return mapping.get(int(value), "star-none")
    except (TypeError, ValueError):
        return "star-none"
