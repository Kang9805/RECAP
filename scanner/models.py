from django.db import models


class Receipt(models.Model):
    STATUS_PENDING = 'pending'
    STATUS_PROCESSING = 'processing'
    STATUS_COMPLETED = 'completed'
    STATUS_FAILED = 'failed'
    STATUS_CHOICES = (
        (STATUS_PENDING, 'Pending'),
        (STATUS_PROCESSING, 'Processing'),
        (STATUS_COMPLETED, 'Completed'),
        (STATUS_FAILED, 'Failed'),
    )

    ERROR_CODE_NONE = ''
    ERROR_CODE_NO_IMAGE = 'no_image'
    ERROR_CODE_ENQUEUE_FAILED = 'enqueue_failed'
    ERROR_CODE_OCR_RETRY = 'ocr_retry'
    ERROR_CODE_OCR_FAILED = 'ocr_failed'
    ERROR_CODE_CHOICES = (
        (ERROR_CODE_NONE, 'None'),
        (ERROR_CODE_NO_IMAGE, 'No image'),
        (ERROR_CODE_ENQUEUE_FAILED, 'Task enqueue failed'),
        (ERROR_CODE_OCR_RETRY, 'OCR retrying'),
        (ERROR_CODE_OCR_FAILED, 'OCR failed'),
    )

    image = models.ImageField(upload_to='receipts/')
    extracted_text = models.TextField(blank=True)
    processing_status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_PENDING)
    processing_error_code = models.CharField(
        max_length=30,
        choices=ERROR_CODE_CHOICES,
        blank=True,
        default=ERROR_CODE_NONE,
    )
    processing_error = models.TextField(blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'Receipt #{self.pk}'


class ReceiptItem(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name='items')
    name = models.CharField(max_length=255)
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def __str__(self):
        return self.name
