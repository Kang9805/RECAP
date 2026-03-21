from decimal import Decimal, InvalidOperation
from datetime import timedelta

from django.db.models import Avg, Count
from django.db.models import Q
from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_date

from django.contrib import messages
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.generic import ListView, DetailView, View
from .models import Receipt, ReceiptItem
from .services.parser import parse_receipt_items_with_unparsed
from .tasks import process_receipt_ocr_task


MAX_UNIT_PRICE = Decimal('99999999.99')
MAX_QUANTITY = 999
MAX_BULK_RETRY_COUNT = 100


def _get_retryable_failed_receipts_queryset():
    configured_codes = getattr(settings, 'OCR_RETRYABLE_ERROR_CODES', None)
    retryable_error_codes = tuple(configured_codes or (
        Receipt.ERROR_CODE_OCR_FAILED,
        Receipt.ERROR_CODE_ENQUEUE_FAILED,
    ))
    return Receipt.objects.filter(
        processing_status=Receipt.STATUS_FAILED,
        processing_error_code__in=retryable_error_codes,
    ).exclude(image='')


class ReceiptUploadView(View):
    template_name = 'scanner/receipt_form.html'

    def get(self, request):
        return render(request, self.template_name)

    def post(self, request):
        files = [f for f in request.FILES.getlist('images') if f]
        if not files:
            messages.error(request, '업로드할 이미지 파일을 1개 이상 선택해주세요.')
            return render(request, self.template_name)

        queued_count = 0
        enqueue_failed_count = 0

        for image in files:
            receipt = Receipt.objects.create(
                image=image,
                processing_status=Receipt.STATUS_PENDING,
                processing_error_code=Receipt.ERROR_CODE_NONE,
                processing_error='',
                extracted_text='',
                processing_attempts=0,
                processing_duration_ms=None,
                processing_started_at=None,
            )

            try:
                process_receipt_ocr_task.delay(receipt.pk)
                queued_count += 1
            except Exception as exc:
                receipt.processing_status = Receipt.STATUS_FAILED
                receipt.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
                receipt.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
                receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])
                enqueue_failed_count += 1

        if queued_count:
            messages.success(request, f'{queued_count}건 업로드 완료, OCR 처리를 시작했습니다.')
        if enqueue_failed_count:
            messages.error(request, f'큐 등록 실패 {enqueue_failed_count}건이 있습니다.')

        return redirect('receipt-list')


class ReceiptListView(ListView):
    model = Receipt
    template_name = 'scanner/receipt_list.html'
    context_object_name = 'receipts'
    paginate_by = 20

    VALID_SORT_OPTIONS = {
        'newest': '-uploaded_at',
        'oldest': 'uploaded_at',
        'slowest': '-processing_duration_ms',
        'fastest': 'processing_duration_ms',
    }

    def get_queryset(self):
        queryset = Receipt.objects.all()

        status = self.request.GET.get('status', '').strip()
        error_code = self.request.GET.get('error_code', '').strip()
        q = self.request.GET.get('q', '').strip()
        uploaded_from = self.request.GET.get('uploaded_from', '').strip()
        uploaded_to = self.request.GET.get('uploaded_to', '').strip()

        valid_statuses = {
            Receipt.STATUS_PENDING,
            Receipt.STATUS_PROCESSING,
            Receipt.STATUS_COMPLETED,
            Receipt.STATUS_FAILED,
        }
        valid_error_codes = {
            Receipt.ERROR_CODE_NO_IMAGE,
            Receipt.ERROR_CODE_ENQUEUE_FAILED,
            Receipt.ERROR_CODE_OCR_RETRY,
            Receipt.ERROR_CODE_OCR_FAILED,
        }

        if status in valid_statuses:
            queryset = queryset.filter(processing_status=status)
        if error_code in valid_error_codes:
            queryset = queryset.filter(processing_error_code=error_code)

        if q:
            keyword_filter = (
                Q(extracted_text__icontains=q)
                | Q(items__name__icontains=q)
                | Q(processing_error__icontains=q)
            )
            if q.isdigit():
                keyword_filter |= Q(pk=int(q))
            queryset = queryset.filter(keyword_filter)

        uploaded_from_date = parse_date(uploaded_from) if uploaded_from else None
        uploaded_to_date = parse_date(uploaded_to) if uploaded_to else None

        if uploaded_from_date:
            queryset = queryset.filter(uploaded_at__date__gte=uploaded_from_date)
        if uploaded_to_date:
            queryset = queryset.filter(uploaded_at__date__lte=uploaded_to_date)

        sort = self.request.GET.get('sort', 'newest')
        ordering = self.VALID_SORT_OPTIONS.get(sort, '-uploaded_at')
        return queryset.distinct().order_by(ordering)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        now = timezone.now()
        day_ago = now - timedelta(hours=24)

        error_code_labels = dict(Receipt.ERROR_CODE_CHOICES)
        total_count = Receipt.objects.count()
        pending_count = Receipt.objects.filter(processing_status=Receipt.STATUS_PENDING).count()
        processing_count = Receipt.objects.filter(processing_status=Receipt.STATUS_PROCESSING).count()
        completed_count = Receipt.objects.filter(processing_status=Receipt.STATUS_COMPLETED).count()
        failed_count = Receipt.objects.filter(processing_status=Receipt.STATUS_FAILED).count()

        context['status_counts'] = {
            'all': total_count,
            Receipt.STATUS_PENDING: pending_count,
            Receipt.STATUS_PROCESSING: processing_count,
            Receipt.STATUS_COMPLETED: completed_count,
            Receipt.STATUS_FAILED: failed_count,
        }
        context['failed_count'] = failed_count
        context['retryable_failed_count'] = _get_retryable_failed_receipts_queryset().count()

        avg_duration = Receipt.objects.filter(
            processing_status=Receipt.STATUS_COMPLETED,
            processing_duration_ms__isnull=False,
        ).aggregate(value=Avg('processing_duration_ms'))['value']

        completed_or_failed = completed_count + failed_count
        success_rate = round((completed_count / completed_or_failed) * 100, 1) if completed_or_failed else 0.0

        recent_counts = {
            'completed': Receipt.objects.filter(
                processing_status=Receipt.STATUS_COMPLETED,
                uploaded_at__gte=day_ago,
            ).count(),
            'failed': Receipt.objects.filter(
                processing_status=Receipt.STATUS_FAILED,
                uploaded_at__gte=day_ago,
            ).count(),
            'uploaded': Receipt.objects.filter(uploaded_at__gte=day_ago).count(),
        }

        context['kpi'] = {
            'avg_duration_ms': int(avg_duration) if avg_duration else None,
            'success_rate': success_rate,
            'recent': recent_counts,
        }

        failed_by_code = (
            Receipt.objects
            .filter(processing_status=Receipt.STATUS_FAILED)
            .exclude(processing_error_code=Receipt.ERROR_CODE_NONE)
            .values('processing_error_code')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        context['failed_count_by_code'] = [
            {
                'processing_error_code': row['processing_error_code'],
                'count': row['count'],
                'label': error_code_labels.get(row['processing_error_code'], row['processing_error_code']),
            }
            for row in failed_by_code
        ]
        context['selected_status'] = self.request.GET.get('status', '').strip()
        context['selected_error_code'] = self.request.GET.get('error_code', '').strip()
        context['selected_q'] = self.request.GET.get('q', '').strip()
        context['selected_uploaded_from'] = self.request.GET.get('uploaded_from', '').strip()
        context['selected_uploaded_to'] = self.request.GET.get('uploaded_to', '').strip()
        context['selected_sort'] = self.request.GET.get('sort', 'newest')
        return context


class ReceiptDetailView(DetailView):
    model = Receipt
    template_name = 'scanner/receipt_detail.html'
    context_object_name = 'receipt'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if self.object.processing_status == Receipt.STATUS_COMPLETED:
            _, unparsed_lines = parse_receipt_items_with_unparsed(self.object.extracted_text or '')
        else:
            unparsed_lines = []
        context['unparsed_lines'] = unparsed_lines
        return context


def receipt_status_api_view(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    return JsonResponse(
        {
            'id': receipt.pk,
            'status': receipt.processing_status,
            'error_code': receipt.processing_error_code,
            'error': receipt.processing_error,
            'attempts': receipt.processing_attempts,
            'duration_ms': receipt.processing_duration_ms,
            'items_count': receipt.items.count(),
        }
    )


def _parse_item_form(request):
    name = request.POST.get('name', '').strip()
    quantity_raw = request.POST.get('quantity', '').strip()
    unit_price_raw = request.POST.get('unit_price', '').strip().replace(',', '')

    if not name:
        raise ValueError('Item name is required')

    quantity = int(quantity_raw)
    unit_price = Decimal(unit_price_raw)

    if quantity <= 0:
        raise ValueError('Quantity must be greater than 0')
    if quantity > MAX_QUANTITY:
        raise ValueError('Quantity is too large')
    if unit_price < 0:
        raise ValueError('Unit price must be 0 or greater')
    if unit_price > MAX_UNIT_PRICE:
        raise ValueError('Unit price is too large')

    return name, quantity, unit_price


@require_POST
def receipt_delete_view(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    receipt.delete()
    return redirect('receipt-list')


@require_POST
def receipt_delete_selected_view(request):
    selected_ids_raw = request.POST.getlist('selected_receipt_ids')
    if not selected_ids_raw:
        messages.info(request, '선택된 영수증이 없습니다.')
        return redirect('receipt-list')

    selected_ids = []
    for value in selected_ids_raw:
        try:
            selected_ids.append(int(value))
        except (TypeError, ValueError):
            continue

    if not selected_ids:
        messages.error(request, '유효한 선택 항목이 없습니다.')
        return redirect('receipt-list')

    queryset = Receipt.objects.filter(pk__in=selected_ids)
    receipt_count = queryset.count()
    queryset.delete()
    if receipt_count:
        messages.success(request, f'{receipt_count}건의 영수증을 삭제했습니다.')
    else:
        messages.info(request, '삭제할 영수증이 없습니다.')

    return redirect('receipt-list')


@require_POST
def receipt_retry_view(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)

    if not receipt.image:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_NO_IMAGE
        receipt.processing_error = 'No receipt image found'
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])
        messages.error(request, '이미지 파일이 없어 재처리를 시작할 수 없습니다.')
        return redirect('receipt-detail', pk=receipt.pk)

    receipt.processing_status = Receipt.STATUS_PENDING
    receipt.processing_error_code = Receipt.ERROR_CODE_NONE
    receipt.processing_error = ''
    receipt.processing_attempts = 0
    receipt.processing_duration_ms = None
    receipt.processing_started_at = None
    receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_attempts', 'processing_duration_ms', 'processing_started_at'])

    try:
        process_receipt_ocr_task.delay(receipt.pk)
        messages.success(request, f'영수증 #{receipt.pk} 재처리를 시작했습니다.')
    except Exception as exc:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
        receipt.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])
        messages.error(request, f'영수증 #{receipt.pk} 재처리 큐 등록에 실패했습니다.')

    return redirect('receipt-detail', pk=receipt.pk)


@require_POST
def receipt_retry_failed_all_view(request):
    failed_receipts = _get_retryable_failed_receipts_queryset().order_by('-uploaded_at')[:MAX_BULK_RETRY_COUNT]
    queued_count = 0
    enqueue_failed_count = 0

    for receipt in failed_receipts:
        receipt.processing_status = Receipt.STATUS_PENDING
        receipt.processing_error_code = Receipt.ERROR_CODE_NONE
        receipt.processing_error = ''
        receipt.processing_attempts = 0
        receipt.processing_duration_ms = None
        receipt.processing_started_at = None
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'processing_attempts', 'processing_duration_ms', 'processing_started_at'])

        try:
            process_receipt_ocr_task.delay(receipt.pk)
            queued_count += 1
        except Exception as exc:
            receipt.processing_status = Receipt.STATUS_FAILED
            receipt.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
            receipt.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
            receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])
            enqueue_failed_count += 1

    if queued_count:
        messages.success(request, f'실패건 {queued_count}건 재처리를 시작했습니다.')
    if enqueue_failed_count:
        messages.error(request, f'큐 등록 실패 {enqueue_failed_count}건이 있습니다.')
    if not queued_count and not enqueue_failed_count:
        messages.info(request, '재처리 가능한 실패건이 없습니다.')

    return redirect('receipt-list')


@require_POST
def receipt_item_create_view(request, receipt_pk):
    receipt = get_object_or_404(Receipt, pk=receipt_pk)
    try:
        name, quantity, unit_price = _parse_item_form(request)
        ReceiptItem.objects.create(
            receipt=receipt,
            name=name,
            quantity=quantity,
            unit_price=unit_price,
        )
    except (ValueError, InvalidOperation):
        pass

    return redirect('receipt-detail', pk=receipt.pk)


@require_POST
def receipt_item_update_view(request, receipt_pk, item_pk):
    receipt = get_object_or_404(Receipt, pk=receipt_pk)
    item = get_object_or_404(ReceiptItem, pk=item_pk, receipt=receipt)
    try:
        name, quantity, unit_price = _parse_item_form(request)
        item.name = name
        item.quantity = quantity
        item.unit_price = unit_price
        item.save(update_fields=['name', 'quantity', 'unit_price'])
    except (ValueError, InvalidOperation):
        pass

    return redirect('receipt-detail', pk=receipt.pk)


@require_POST
def receipt_item_delete_view(request, receipt_pk, item_pk):
    receipt = get_object_or_404(Receipt, pk=receipt_pk)
    item = get_object_or_404(ReceiptItem, pk=item_pk, receipt=receipt)
    item.delete()
    return redirect('receipt-detail', pk=receipt.pk)