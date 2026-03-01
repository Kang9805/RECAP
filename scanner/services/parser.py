import re
from decimal import Decimal, InvalidOperation


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
    '매장',
    '주소',
    '사업장',
    '거래',
    '일시',
    '주문',
    '포인트',
    '현금',
    '신용',
    '영수증',
    '계산대',
    '쿠폰',
    '할인합계',
)

NOISE_LINE_PATTERN = re.compile(r'^[\s\-_=*~`]+$')
MAX_UNIT_PRICE = Decimal('99999999.99')
MAX_QUANTITY = 999


def _to_decimal(value: str) -> Decimal | None:
    normalized = value.replace(',', '').strip()
    if not normalized:
        return None
    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation:
        return None

    if decimal_value < 0 or decimal_value > MAX_UNIT_PRICE:
        return None
    return decimal_value


def _normalize_line(line: str) -> str:
    line = line.replace('\u00a0', ' ')
    line = re.sub(r'[·•●▪◆▶▷]+', ' ', line)
    line = re.sub(r'\s+', ' ', line).strip()
    return line


def _normalize_numeric_token(token: str) -> str:
    corrected = token.translate(
        str.maketrans(
            {
                'O': '0',
                'o': '0',
                'I': '1',
                'l': '1',
                '|': '1',
                'S': '5',
                's': '5',
                'B': '8',
            }
        )
    )
    return re.sub(r'[^\d,]', '', corrected)


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    if NOISE_LINE_PATTERN.match(line):
        return True
    return False


def _is_item_name(name: str) -> bool:
    lowered = name.lower()
    if any(keyword in lowered for keyword in SKIP_KEYWORDS):
        return False
    if re.search(r'\d{2,}[-/:]\d{1,2}[-/:]\d{1,2}', name):
        return False
    if re.search(r'\d{1,2}:\d{2}', name):
        return False
    if ':' in name:
        return False
    if len(name.strip()) < 2:
        return False
    return bool(re.search(r'[가-힣a-zA-Z]', name))


def _extract_item_from_line(line: str) -> dict | None:
    qty_unit_total_pattern = re.compile(
        r'^(?P<name>.+?)\s+(?P<qty>\d{1,2})\s+(?P<unit>\d[\d,]*)\s+(?P<total>\d[\d,]*)$'
    )
    qty_total_pattern = re.compile(
        r'^(?P<name>.+?)\s+(?P<qty>\d{1,2})\s+(?P<price>\d[\d,]*)$'
    )
    price_only_pattern = re.compile(r'^(?P<name>.+?)\s+(?P<price>\d[\d,]*)$')

    match = qty_unit_total_pattern.match(line)
    if match:
        name = match.group('name').strip()
        quantity = int(match.group('qty'))
        unit_price = _to_decimal(_normalize_numeric_token(match.group('unit')))
        total_price = _to_decimal(_normalize_numeric_token(match.group('total')))

        if quantity <= 0 or quantity > MAX_QUANTITY:
            return None
        if unit_price is None or total_price is None:
            return None

        if quantity > 0 and total_price > 0:
            inferred = (total_price / quantity).quantize(Decimal('1'))
            if inferred > 0 and inferred <= MAX_UNIT_PRICE and abs(inferred - unit_price) > 100:
                unit_price = inferred

        if _is_item_name(name):
            return {
                'name': name,
                'quantity': max(quantity, 1),
                'unit_price': unit_price,
            }
        return None

    match = qty_total_pattern.match(line)
    if match:
        name = match.group('name').strip()
        quantity = int(match.group('qty'))
        total_price = _to_decimal(_normalize_numeric_token(match.group('price')))

        if quantity <= 0 or quantity > MAX_QUANTITY:
            return None
        if total_price is None:
            return None

        if _is_item_name(name) and quantity > 0:
            unit_price = (total_price / quantity).quantize(Decimal('1'))
            if unit_price <= 0 or unit_price > MAX_UNIT_PRICE:
                return None
            return {
                'name': name,
                'quantity': quantity,
                'unit_price': unit_price,
            }
        return None

    match = price_only_pattern.match(line)
    if match:
        name = match.group('name').strip()
        price = _to_decimal(_normalize_numeric_token(match.group('price')))
        if price is None:
            return None

        if _is_item_name(name):
            return {
                'name': name,
                'quantity': 1,
                'unit_price': price,
            }
        return None

    return None


def parse_receipt_items(extracted_text: str) -> list[dict]:
    items = []
    lines = [_normalize_line(line) for line in extracted_text.splitlines()]

    for line in lines:
        if _is_noise_line(line):
            continue
        parsed_item = _extract_item_from_line(line)
        if parsed_item:
            items.append(parsed_item)

    return items
