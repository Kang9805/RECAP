from unittest.mock import patch

from datetime import timedelta
from io import StringIO

from django.core.management import call_command
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Receipt
from .tasks import _is_non_retryable_ocr_error, process_receipt_ocr_task
from .views import _get_retryable_failed_receipts_queryset


def _fake_image_file(name='receipt.jpg'):
	# Minimal valid payload for ImageField path tests.
	return SimpleUploadedFile(name, b'fake-image-bytes', content_type='image/jpeg')


class RetryableQuerysetTests(TestCase):
	def test_get_retryable_failed_receipts_queryset_filters_expected_records(self):
		retryable_1 = Receipt.objects.create(
			image=_fake_image_file('r1.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
		)
		retryable_2 = Receipt.objects.create(
			image=_fake_image_file('r2.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_ENQUEUE_FAILED,
		)
		Receipt.objects.create(
			image=_fake_image_file('r3.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_NO_IMAGE,
		)
		Receipt.objects.create(
			image=_fake_image_file('r4.jpg'),
			processing_status=Receipt.STATUS_COMPLETED,
			processing_error_code=Receipt.ERROR_CODE_NONE,
		)

		ids = set(_get_retryable_failed_receipts_queryset().values_list('id', flat=True))
		self.assertEqual(ids, {retryable_1.id, retryable_2.id})


class RetryViewsTests(TestCase):
	@patch('scanner.views.process_receipt_ocr_task.delay')
	def test_retry_failed_all_requeues_only_retryable_failed(self, delay_mock):
		retryable = Receipt.objects.create(
			image=_fake_image_file('x1.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
			processing_error='old error',
		)
		not_retryable = Receipt.objects.create(
			image=_fake_image_file('x2.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_NO_IMAGE,
			processing_error='missing image',
		)

		response = self.client.post(reverse('receipt-retry-failed-all'))
		self.assertEqual(response.status_code, 302)

		retryable.refresh_from_db()
		not_retryable.refresh_from_db()

		self.assertEqual(retryable.processing_status, Receipt.STATUS_PENDING)
		self.assertEqual(retryable.processing_error_code, Receipt.ERROR_CODE_NONE)
		self.assertEqual(retryable.processing_error, '')

		self.assertEqual(not_retryable.processing_status, Receipt.STATUS_FAILED)
		self.assertEqual(not_retryable.processing_error_code, Receipt.ERROR_CODE_NO_IMAGE)

		delay_mock.assert_called_once_with(retryable.pk)


class ReceiptListFilterTests(TestCase):
	def test_list_filters_by_status_and_error_code(self):
		target = Receipt.objects.create(
			image=_fake_image_file('f1.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
		)
		Receipt.objects.create(
			image=_fake_image_file('f2.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_ENQUEUE_FAILED,
		)
		Receipt.objects.create(
			image=_fake_image_file('f3.jpg'),
			processing_status=Receipt.STATUS_COMPLETED,
			processing_error_code=Receipt.ERROR_CODE_NONE,
		)

		response = self.client.get(
			reverse('receipt-list'),
			{'status': Receipt.STATUS_FAILED, 'error_code': Receipt.ERROR_CODE_OCR_FAILED},
		)
		self.assertEqual(response.status_code, 200)

		receipts = list(response.context['receipts'])
		self.assertEqual(len(receipts), 1)
		self.assertEqual(receipts[0].id, target.id)

		self.assertIn('status_counts', response.context)
		self.assertIn('failed_count_by_code', response.context)


class ReceiptStatusApiTests(TestCase):
	def test_status_api_returns_expected_payload_shape(self):
		receipt = Receipt.objects.create(
			image=_fake_image_file('s1.jpg'),
			processing_status=Receipt.STATUS_PROCESSING,
			processing_error_code=Receipt.ERROR_CODE_NONE,
			processing_attempts=2,
			processing_duration_ms=None,
		)

		response = self.client.get(reverse('receipt-status-api', args=[receipt.pk]))
		self.assertEqual(response.status_code, 200)

		payload = response.json()
		self.assertEqual(
			set(payload.keys()),
			{'id', 'status', 'error_code', 'error', 'attempts', 'duration_ms', 'items_count'},
		)
		self.assertEqual(payload['id'], receipt.pk)
		self.assertEqual(payload['status'], Receipt.STATUS_PROCESSING)
		self.assertEqual(payload['error_code'], Receipt.ERROR_CODE_NONE)
		self.assertEqual(payload['attempts'], 2)
		self.assertIsNone(payload['duration_ms'])
		self.assertEqual(payload['items_count'], 0)

	def test_status_api_includes_failure_info(self):
		receipt = Receipt.objects.create(
			image=_fake_image_file('s2.jpg'),
			processing_status=Receipt.STATUS_FAILED,
			processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
			processing_error='OCR failed after retries: timeout',
			processing_attempts=4,
			processing_duration_ms=12345,
		)

		response = self.client.get(reverse('receipt-status-api', args=[receipt.pk]))
		self.assertEqual(response.status_code, 200)

		payload = response.json()
		self.assertEqual(payload['status'], Receipt.STATUS_FAILED)
		self.assertEqual(payload['error_code'], Receipt.ERROR_CODE_OCR_FAILED)
		self.assertIn('OCR failed', payload['error'])
		self.assertEqual(payload['attempts'], 4)
		self.assertEqual(payload['duration_ms'], 12345)


class OCRTaskErrorHandlingTests(TestCase):
	def test_is_non_retryable_ocr_error_detects_missing_image_value_error(self):
		exc = ValueError('Failed to load image: /tmp/missing.jpg')
		self.assertTrue(_is_non_retryable_ocr_error(exc))

	def test_task_marks_no_image_code_without_retry_for_missing_image_error(self):
		receipt = Receipt.objects.create(image=_fake_image_file('z1.jpg'))

		with patch('scanner.tasks.extract_text_from_receipt', side_effect=ValueError('Failed to load image: /tmp/missing.jpg')):
			process_receipt_ocr_task.run(receipt.id)

		receipt.refresh_from_db()
		self.assertEqual(receipt.processing_status, Receipt.STATUS_FAILED)
		self.assertEqual(receipt.processing_error_code, Receipt.ERROR_CODE_NO_IMAGE)
		self.assertIn('Non-retryable OCR error', receipt.processing_error)

	def test_task_sets_processing_started_at_during_processing(self):
		receipt = Receipt.objects.create(image=_fake_image_file('z2.jpg'))

		with patch('scanner.tasks.extract_text_from_receipt', return_value='sample text'), patch(
			'scanner.tasks.parse_receipt_items_with_unparsed', return_value=([], [])
		):
			process_receipt_ocr_task.run(receipt.id)

		receipt.refresh_from_db()
		self.assertEqual(receipt.processing_status, Receipt.STATUS_COMPLETED)
		self.assertIsNotNone(receipt.processing_started_at)


class StuckReceiptCommandTests(TestCase):
	def test_mark_stuck_receipts_marks_only_old_processing_rows(self):
		now = timezone.now()
		stuck = Receipt.objects.create(
			image=_fake_image_file('m1.jpg'),
			processing_status=Receipt.STATUS_PROCESSING,
			processing_started_at=now - timedelta(minutes=40),
		)
		fresh = Receipt.objects.create(
			image=_fake_image_file('m2.jpg'),
			processing_status=Receipt.STATUS_PROCESSING,
			processing_started_at=now - timedelta(minutes=5),
		)

		out = StringIO()
		call_command('mark_stuck_receipts', '--minutes', '20', stdout=out)

		stuck.refresh_from_db()
		fresh.refresh_from_db()

		self.assertEqual(stuck.processing_status, Receipt.STATUS_FAILED)
		self.assertEqual(stuck.processing_error_code, Receipt.ERROR_CODE_OCR_FAILED)
		self.assertEqual(stuck.processing_error, 'Stuck processing timeout exceeded')
		self.assertIsNone(stuck.processing_started_at)

		self.assertEqual(fresh.processing_status, Receipt.STATUS_PROCESSING)
