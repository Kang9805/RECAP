from decimal import Decimal, InvalidOperation
from django import template

register = template.Library()


@register.filter
def mul(value, arg):
    try:
        return Decimal(str(value)) * Decimal(str(arg))
    except (InvalidOperation, TypeError, ValueError):
        return 0
