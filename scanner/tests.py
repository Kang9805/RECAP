from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

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
