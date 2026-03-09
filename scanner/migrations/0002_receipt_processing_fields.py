from django.db import migrations, models


def set_processing_status_for_existing_receipts(apps, schema_editor):
    Receipt = apps.get_model('scanner', 'Receipt')
    Receipt.objects.exclude(extracted_text='').update(processing_status='completed')


class Migration(migrations.Migration):

    dependencies = [
        ('scanner', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='processing_error',
            field=models.TextField(blank=True),
        ),
        migrations.AddField(
            model_name='receipt',
            name='processing_status',
            field=models.CharField(
                choices=[
                    ('pending', 'Pending'),
                    ('processing', 'Processing'),
                    ('completed', 'Completed'),
                    ('failed', 'Failed'),
                ],
                default='pending',
                max_length=20,
            ),
        ),
        migrations.RunPython(
            set_processing_status_for_existing_receipts,
            migrations.RunPython.noop,
        ),
    ]
