from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanner', '0003_receipt_processing_error_code'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='processing_attempts',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name='receipt',
            name='processing_duration_ms',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
