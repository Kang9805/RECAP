from django.contrib import admin, messages
from django.db.models import Count
from django.utils.html import format_html

from .models import Receipt, ReceiptItem
from .tasks import process_receipt_ocr_task


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0
    fields = ('name', 'quantity', 'unit_price')


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'processing_status',
        'processing_error_code',
        'processing_attempts',
        'processing_duration_ms',
        'item_count',
        'uploaded_at',
    )
    list_filter = ('processing_status', 'processing_error_code', 'uploaded_at')
    search_fields = ('=id', 'extracted_text', 'processing_error', 'items__name')
    readonly_fields = (
        'uploaded_at',
        'processing_started_at',
        'processing_attempts',
        'processing_duration_ms',
        'receipt_image_preview',
        'extracted_text',
        'processing_error',
    )
    actions = ('retry_selected_failed_receipts',)
    date_hierarchy = 'uploaded_at'
    inlines = [ReceiptItemInline]
    fieldsets = (
        ('기본 정보', {
            'fields': ('image', 'receipt_image_preview', 'uploaded_at'),
        }),
        ('처리 상태', {
            'fields': (
                'processing_status',
                'processing_error_code',
                'processing_error',
                'processing_attempts',
                'processing_duration_ms',
                'processing_started_at',
            ),
        }),
        ('OCR 결과', {
            'fields': ('extracted_text',),
        }),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset.annotate(_item_count=Count('items'))

    @admin.display(description='품목 수', ordering='_item_count')
    def item_count(self, obj):
        return obj._item_count

    @admin.display(description='영수증 이미지')
    def receipt_image_preview(self, obj):
        if not obj.pk or not obj.image:
            return '-'
        return format_html(
            '<a href="{}" target="_blank" rel="noopener">원본 열기</a>',
            obj.image.url,
        )

    @admin.action(description='선택한 실패 영수증 재처리')
    def retry_selected_failed_receipts(self, request, queryset):
        failed_receipts = queryset.filter(processing_status=Receipt.STATUS_FAILED).exclude(image='')
        updated_count = 0

        for receipt in failed_receipts:
            receipt.processing_status = Receipt.STATUS_PENDING
            receipt.processing_error_code = Receipt.ERROR_CODE_NONE
            receipt.processing_error = ''
            receipt.processing_started_at = None
            receipt.save(update_fields=[
                'processing_status',
                'processing_error_code',
                'processing_error',
                'processing_started_at',
            ])
            process_receipt_ocr_task.delay(receipt.pk)
            updated_count += 1

        if updated_count:
            self.message_user(request, f'{updated_count}건 재처리를 시작했습니다.', level=messages.SUCCESS)
            return

        self.message_user(request, '재처리할 실패 영수증이 없습니다.', level=messages.WARNING)


@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_select_related = ('receipt',)
    list_display = ('id', 'name', 'quantity', 'unit_price', 'receipt')
    list_filter = ('receipt__processing_status',)
    search_fields = ('name', '=receipt__id', 'receipt__extracted_text')
