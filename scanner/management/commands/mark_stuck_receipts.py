from django.conf import settings
from django.core.management.base import BaseCommand

from scanner.tasks import mark_stuck_receipts_as_failed


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

        updated = mark_stuck_receipts_as_failed(threshold_minutes=threshold_minutes)

        self.stdout.write(
            self.style.SUCCESS(
                f'Marked {updated} stuck receipt(s) as failed (threshold={threshold_minutes}m).'
            )
        )
