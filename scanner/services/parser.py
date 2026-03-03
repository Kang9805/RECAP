import re
from decimal import Decimal, InvalidOperation


SKIP_KEYWORDS = (
    '합계',
    '총액',
    '부가',
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
    '고객',
    '고객수',
    '객수',
    '렉수',
    '주문자',
    '수탈',
)

TABLE_HEADER_HINTS = ('단가', '수량', '수향', '수탈', '금액', '고액')

NOISE_LINE_PATTERN = re.compile(r'^[\s\-_=*~`]+$')
MAX_UNIT_PRICE = Decimal('99999999.99')
MIN_UNIT_PRICE = Decimal('100')
MAX_QUANTITY = 50


def _to_decimal(value: str) -> Decimal | None:
    normalized = value.replace(',', '').replace('.', '').strip()
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
    return re.sub(r'[^\d,.]', '', corrected)


def _is_noise_line(line: str) -> bool:
    if not line:
        return True
    if NOISE_LINE_PATTERN.match(line):
        return True
    return False


def _is_barcode_like_line(line: str) -> bool:
    compact = re.sub(r'\s+', '', line)
    digits = re.sub(r'\D', '', compact)
    if len(digits) >= 8 and len(digits) >= int(len(compact) * 0.7):
        return True
    return False


def _is_item_name(name: str) -> bool:
    lowered = name.lower()
    compact = re.sub(r'\s+', '', lowered)
    if any(keyword in lowered or keyword.replace(' ', '') in compact for keyword in SKIP_KEYWORDS):
        return False
    if re.search(r'\d{2,}[-/:]\d{1,2}[-/:]\d{1,2}', name):
        return False
    if re.search(r'\d{1,2}:\d{2}', name):
        return False
    if ':' in name:
        return False
    if len(name.strip()) < 2:
        return False
    if len(name.strip()) > 24:
        return False
    if _is_barcode_like_line(name):
        return False
    if len(re.findall(r'[가-힣]', name)) < 1:
        return False
    return True


def _is_candidate_name_line(name: str) -> bool:
    if not _is_item_name(name):
        return False
    if len(name.split()) > 3:
        return False
    if re.search(r'\d', name):
        return False
    if re.search(r'[시군구읍면동]$', name.strip()):
        return False
    return True


def _is_table_header_line(line: str) -> bool:
    normalized = re.sub(r'\s+', '', line)
    if normalized in TABLE_HEADER_HINTS:
        return True
    return sum(1 for hint in TABLE_HEADER_HINTS if hint in line) >= 2


def _is_total_like_line(line: str) -> bool:
    lowered = re.sub(r'\s+', '', line.lower())
    return any(keyword.replace(' ', '') in lowered for keyword in ('합계', '총액', '부가세', '과세', '면세', '결제', '카드'))


def _is_indexed_name_line(line: str) -> bool:
    return bool(re.match(r'^\d{1,3}\s+[가-힣A-Za-z].+', line))


def _clean_item_name(name: str) -> str:
    cleaned = re.sub(r'^\d{1,3}\s+', '', name).strip()
    cleaned = re.sub(r'\(.*?\)$', '', cleaned).strip()
    return cleaned


def _extract_numeric_row(line: str) -> tuple[int, Decimal] | None:
    normalized = _normalize_line(line)
    numeric_tokens = re.findall(r'[\dOoIl|SsB][\dOoIl|SsB,\.]*', normalized)
    parsed_numbers = []

    for token in numeric_tokens:
        value = _to_decimal(_normalize_numeric_token(token))
        if value is not None and value > 0:
            parsed_numbers.append(value)

    if len(parsed_numbers) < 2:
        return None

    qty = None
    total_price = None

    if len(parsed_numbers) == 2:
        first, second = parsed_numbers

        if first <= MAX_QUANTITY and second >= MIN_UNIT_PRICE:
            qty = int(first)
            total_price = second
        elif second <= MAX_QUANTITY and first >= MIN_UNIT_PRICE:
            qty = int(second)
            total_price = first * qty
        else:
            qty = 1
            total_price = max(first, second)
    else:
        tail = parsed_numbers[-3:]
        first, second, third = tail

        if second <= MAX_QUANTITY and third >= MIN_UNIT_PRICE:
            qty = int(second)
            total_price = third
        elif first <= MAX_QUANTITY and third >= MIN_UNIT_PRICE:
            qty = int(first)
            total_price = third
        elif third <= MAX_QUANTITY and second >= MIN_UNIT_PRICE:
            qty = int(third)
            total_price = second * qty
        else:
            qty = int(parsed_numbers[-2])
            total_price = parsed_numbers[-1]

    if qty is None or qty <= 0 or qty > MAX_QUANTITY:
        qty = 1

    if total_price is None or total_price <= 0 or total_price > MAX_UNIT_PRICE:
        return None

    unit_price = (total_price / qty).quantize(Decimal('1'))
    if unit_price <= 0 or unit_price > MAX_UNIT_PRICE:
        return None
    if unit_price < MIN_UNIT_PRICE:
        return None

    return qty, unit_price


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
        name = _clean_item_name(match.group('name').strip())
        quantity = int(match.group('qty'))
        unit_price = _to_decimal(_normalize_numeric_token(match.group('unit')))
        total_price = _to_decimal(_normalize_numeric_token(match.group('total')))

        if quantity <= 0 or quantity > MAX_QUANTITY:
            return None
        if unit_price is None or total_price is None:
            return None
        if unit_price < MIN_UNIT_PRICE or total_price < MIN_UNIT_PRICE:
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
        name = _clean_item_name(match.group('name').strip())
        quantity = int(match.group('qty'))
        total_price = _to_decimal(_normalize_numeric_token(match.group('price')))

        if quantity <= 0 or quantity > MAX_QUANTITY:
            return None
        if total_price is None:
            return None
        if total_price < MIN_UNIT_PRICE:
            return None

        if _is_item_name(name) and quantity > 0:
            unit_price = (total_price / quantity).quantize(Decimal('1'))
            if unit_price <= 0 or unit_price > MAX_UNIT_PRICE:
                return None
            if unit_price < MIN_UNIT_PRICE:
                return None
            return {
                'name': name,
                'quantity': quantity,
                'unit_price': unit_price,
            }
        return None

    match = price_only_pattern.match(line)
    if match:
        name = _clean_item_name(match.group('name').strip())
        price = _to_decimal(_normalize_numeric_token(match.group('price')))
        if price is None:
            return None
        if price < MIN_UNIT_PRICE:
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
    items, _ = parse_receipt_items_with_unparsed(extracted_text)
    return items


def parse_receipt_items_with_unparsed(extracted_text: str) -> tuple[list[dict], list[str]]:
    items = []
    unparsed_lines = []
    lines = [_normalize_line(line) for line in extracted_text.splitlines()]
    pending_name = None
    pending_from_index = False
    in_item_table = False

    for line in lines:
        if _is_noise_line(line):
            continue

        if _is_table_header_line(line):
            in_item_table = True
            continue

        if in_item_table and _is_total_like_line(line):
            in_item_table = False

        if not in_item_table and _is_total_like_line(line):
            continue

        numeric_row = _extract_numeric_row(line)
        if pending_name and numeric_row:
            qty, unit_price = numeric_row
            loose_name_ok = pending_from_index and bool(re.search(r'[가-힣]', pending_name))
            if _is_item_name(pending_name) or _is_candidate_name_line(pending_name) or loose_name_ok:
                items.append(
                    {
                        'name': pending_name,
                        'quantity': qty,
                        'unit_price': unit_price,
                    }
                )
                pending_name = None
                pending_from_index = False
                continue

        if _is_barcode_like_line(line):
            continue

        # 헤더 인식 실패 대비: 인덱스+상품명 라인은 항상 후보로 본다.
        if _is_indexed_name_line(line):
            cleaned_name = _clean_item_name(line)
            if cleaned_name and not _is_total_like_line(cleaned_name):
                pending_name = cleaned_name
                pending_from_index = True
                continue

        if not in_item_table and not _is_item_name(line):
            continue

        parsed_item = _extract_item_from_line(line)
        if parsed_item:
            items.append(parsed_item)
            pending_name = None
            pending_from_index = False
        else:
            cleaned_name = _clean_item_name(line)

            if cleaned_name and (_is_candidate_name_line(cleaned_name) or (in_item_table and len(cleaned_name) >= 2)):
                pending_name = cleaned_name
                pending_from_index = False
            else:
                unparsed_lines.append(line)

    if pending_name:
        unparsed_lines.append(pending_name)

    return items, unparsed_lines
