from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanner', '0002_receipt_processing_fields'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='processing_error_code',
            field=models.CharField(
                blank=True,
                choices=[
                    ('', 'None'),
                    ('no_image', 'No image'),
                    ('enqueue_failed', 'Task enqueue failed'),
                    ('ocr_retry', 'OCR retrying'),
                    ('ocr_failed', 'OCR failed'),
                ],
                default='',
                max_length=30,
            ),
        ),
    ]
