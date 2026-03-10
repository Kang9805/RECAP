from datetime import timedelta

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from scanner.models import Receipt


class Command(BaseCommand):
    help = 'Mark stuck processing receipts as failed when they exceed processing timeout.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--minutes',
            type=int,
            default=None,
            help='Override stuck threshold in minutes (default from OCR_PROCESSING_STUCK_MINUTES).',
        )

    def handle(self, *args, **options):
        threshold_minutes = options['minutes']
        if threshold_minutes is None:
            threshold_minutes = int(getattr(settings, 'OCR_PROCESSING_STUCK_MINUTES', 20))

        cutoff = timezone.now() - timedelta(minutes=threshold_minutes)

        stuck_receipts = Receipt.objects.filter(
            processing_status=Receipt.STATUS_PROCESSING,
            processing_started_at__isnull=False,
            processing_started_at__lte=cutoff,
        )

        updated = stuck_receipts.update(
            processing_status=Receipt.STATUS_FAILED,
            processing_error_code=Receipt.ERROR_CODE_OCR_FAILED,
            processing_error='Stuck processing timeout exceeded',
            processing_started_at=None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f'Marked {updated} stuck receipt(s) as failed (threshold={threshold_minutes}m).'
            )
        )
