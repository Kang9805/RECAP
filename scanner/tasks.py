from django.db import transaction

from celery import shared_task

from .models import Receipt, ReceiptItem
from .services.ocr import extract_text_from_receipt
from .services.parser import parse_receipt_items_with_unparsed


@shared_task(bind=True)
def process_receipt_ocr_task(self, receipt_id: int):
    try:
        receipt = Receipt.objects.get(pk=receipt_id)
    except Receipt.DoesNotExist:
        return

    if not receipt.image:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error = 'No receipt image found'
        receipt.save(update_fields=['processing_status', 'processing_error'])
        return

    receipt.processing_status = Receipt.STATUS_PROCESSING
    receipt.processing_error = ''
    receipt.save(update_fields=['processing_status', 'processing_error'])

    try:
        text = extract_text_from_receipt(receipt.image.path)
        parsed_items, _ = parse_receipt_items_with_unparsed(text)

        with transaction.atomic():
            receipt.extracted_text = text
            receipt.processing_status = Receipt.STATUS_COMPLETED
            receipt.processing_error = ''
            receipt.save(update_fields=['extracted_text', 'processing_status', 'processing_error'])

            receipt.items.all().delete()
            receipt_items = [
                ReceiptItem(
                    receipt=receipt,
                    name=item['name'],
                    quantity=item['quantity'],
                    unit_price=item['unit_price'],
                )
                for item in parsed_items
            ]
            if receipt_items:
                ReceiptItem.objects.bulk_create(receipt_items)
    except Exception as exc:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error = str(exc)[:500]
        receipt.save(update_fields=['processing_status', 'processing_error'])
