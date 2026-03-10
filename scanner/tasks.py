from django.db import transaction
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import random
import logging

from celery import shared_task

from .models import Receipt, ReceiptItem
from .services.ocr import extract_text_from_receipt
from .services.parser import parse_receipt_items_with_unparsed


MAX_RETRIES = max(0, int(getattr(settings, 'OCR_TASK_MAX_RETRIES', 3)))
RETRY_BASE_SECONDS = max(1, int(getattr(settings, 'OCR_TASK_RETRY_BASE_SECONDS', 2)))
RETRY_JITTER_SECONDS = max(0, int(getattr(settings, 'OCR_TASK_RETRY_JITTER_SECONDS', 1)))
logger = logging.getLogger(__name__)


def mark_stuck_receipts_as_failed(threshold_minutes: int | None = None) -> int:
    if threshold_minutes is None:
        threshold_minutes = int(getattr(settings, 'OCR_PROCESSING_STUCK_MINUTES', 20))

    cutoff = timezone.now() - timedelta(minutes=threshold_minutes)
    updated = Receipt.objects.filter(
        processing_status=Receipt.STATUS_PROCESSING,
        processing_started_at__isnull=False,
        processing_started_at__lte=cutoff,
    ).update(
        processing_status=Receipt.STATUS_FAILED,
        processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
        processing_error='Stuck processing timeout exceeded',
        processing_started_at=None,
    )
    return updated


def _is_non_retryable_ocr_error(exc: Exception) -> bool:
    if isinstance(exc, ValueError) and 'Failed to load image:' in str(exc):
        return True
    return False


@shared_task(bind=True, max_retries=MAX_RETRIES)
def process_receipt_ocr_task(self, receipt_id: int):
    started_at = timezone.now()

    try:
        receipt = Receipt.objects.get(pk=receipt_id)
    except Receipt.DoesNotExist:
        return

    if not receipt.image:
        elapsed_ms = int((timezone.now() - started_at).total_seconds() * 1000)
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_NO_IMAGE
        receipt.processing_error = 'No receipt image found'
        receipt.processing_attempts = self.request.retries + 1
        receipt.processing_duration_ms = elapsed_ms
        receipt.processing_started_at = None
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_attempts', 'processing_duration_ms', 'processing_started_at'])
        logger.warning('OCR task failed: no image on receipt_id=%s', receipt_id)
        return

    receipt.processing_status = Receipt.STATUS_PROCESSING
    receipt.processing_error_code = Receipt.ERROR_CODE_NONE
    receipt.processing_error = ''
    receipt.processing_attempts = self.request.retries + 1
    receipt.processing_started_at = timezone.now()
    receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_attempts', 'processing_started_at'])
    logger.info('OCR task started receipt_id=%s attempt=%s', receipt_id, self.request.retries + 1)

    try:
        text = extract_text_from_receipt(receipt.image.path)
        parsed_items, _ = parse_receipt_items_with_unparsed(text)

        with transaction.atomic():
            elapsed_ms = int((timezone.now() - started_at).total_seconds() * 1000)
            receipt.extracted_text = text
            receipt.processing_status = Receipt.STATUS_COMPLETED
            receipt.processing_error_code = Receipt.ERROR_CODE_NONE
            receipt.processing_error = ''
            receipt.processing_duration_ms = elapsed_ms
            receipt.save(update_fields=['extracted_text', 'processing_status', 'processing_error_code', 'processing_error', 'processing_duration_ms'])
            logger.info('OCR task completed receipt_id=%s duration_ms=%s items=%s', receipt_id, elapsed_ms, len(parsed_items))

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
        current_retry = self.request.retries

        if _is_non_retryable_ocr_error(exc):
            elapsed_ms = int((timezone.now() - started_at).total_seconds() * 1000)
            receipt.processing_status = Receipt.STATUS_FAILED
            receipt.processing_error_code = Receipt.ERROR_CODE_NO_IMAGE
            receipt.processing_error = f'Non-retryable OCR error: {str(exc)[:300]}'
            receipt.processing_duration_ms = elapsed_ms
            receipt.processing_started_at = None
            receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_duration_ms', 'processing_started_at'])
            logger.error('OCR non-retryable error receipt_id=%s error=%s', receipt_id, str(exc)[:200])
            return

        if current_retry < self.max_retries:
            retry_in = RETRY_BASE_SECONDS * (2 ** current_retry)
            if RETRY_JITTER_SECONDS > 0:
                retry_in += random.randint(0, RETRY_JITTER_SECONDS)
            receipt.processing_status = Receipt.STATUS_PENDING
            receipt.processing_error_code = Receipt.ERROR_CODE_OCR_RETRY
            receipt.processing_error = (
                f'Temporary OCR error. Retry {current_retry + 1}/{self.max_retries} '
                f'in {retry_in}s: {str(exc)[:200]}'
            )
            receipt.processing_started_at = None
            receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_started_at'])
            logger.warning(
                'OCR temporary error receipt_id=%s retry=%s/%s in=%ss error=%s',
                receipt_id,
                current_retry + 1,
                self.max_retries,
                retry_in,
                str(exc)[:120],
            )
            raise self.retry(exc=exc, countdown=retry_in)

        elapsed_ms = int((timezone.now() - started_at).total_seconds() * 1000)
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_OCR_FAILED
        receipt.processing_error = f'OCR failed after retries: {str(exc)[:300]}'
        receipt.processing_duration_ms = elapsed_ms
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_duration_ms'])
        logger.error('OCR task failed receipt_id=%s duration_ms=%s error=%s', receipt_id, elapsed_ms, str(exc)[:200])


@shared_task
def mark_stuck_receipts_task():
    updated = mark_stuck_receipts_as_failed()
    logger.info('Stuck receipt cleanup executed updated=%s', updated)
    return updated
