from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('scanner', '0004_receipt_processing_metrics'),
    ]

    operations = [
        migrations.AddField(
            model_name='receipt',
            name='processing_started_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
