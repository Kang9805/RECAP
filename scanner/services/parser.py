import re
from decimal import Decimal


SKIP_KEYWORDS = (
    '합계',
    '총액',
    '부가세',
    '과세',
    '면세',
    '카드',
    '승인',
    '사업자',
    '대표',
    '전화',
    'tel',
)


def _to_decimal(value: str) -> Decimal:
    return Decimal(value.replace(',', ''))


def _is_item_name(name: str) -> bool:
    lowered = name.lower()
    if any(keyword in lowered for keyword in SKIP_KEYWORDS):
        return False
    return bool(re.search(r'[가-힣a-zA-Z]', name))


def parse_receipt_items(extracted_text: str) -> list[dict]:
    items = []
    lines = [re.sub(r'\s+', ' ', line).strip() for line in extracted_text.splitlines()]

    qty_price_pattern = re.compile(r'^(?P<name>.+?)\s+(?P<qty>\d{1,3})\s+(?P<price>\d[\d,]*)$')
    price_only_pattern = re.compile(r'^(?P<name>.+?)\s+(?P<price>\d[\d,]*)$')

    for line in lines:
        if not line:
            continue

        qty_price_match = qty_price_pattern.match(line)
        if qty_price_match:
            name = qty_price_match.group('name').strip()
            quantity = int(qty_price_match.group('qty'))
            unit_price = _to_decimal(qty_price_match.group('price'))

            if _is_item_name(name):
                items.append(
                    {
                        'name': name,
                        'quantity': max(quantity, 1),
                        'unit_price': unit_price,
                    }
                )
            continue

        price_only_match = price_only_pattern.match(line)
        if price_only_match:
            name = price_only_match.group('name').strip()
            unit_price = _to_decimal(price_only_match.group('price'))

            if _is_item_name(name):
                items.append(
                    {
                        'name': name,
                        'quantity': 1,
                        'unit_price': unit_price,
                    }
                )

    return items
