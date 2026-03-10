from decimal import Decimal, InvalidOperation
from django.db.models import Count

from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, DetailView
from django.urls import reverse_lazy
from .models import Receipt, ReceiptItem
from .services.parser import parse_receipt_items_with_unparsed
from .tasks import process_receipt_ocr_task


MAX_UNIT_PRICE = Decimal('99999999.99')
MAX_QUANTITY = 999


class ReceiptUploadView(CreateView):
    model = Receipt
    fields = ['image']
    template_name = 'scanner/receipt_form.html'
    success_url = reverse_lazy('receipt-list')
    
    def form_valid(self, form):
        response = super().form_valid(form)

        if self.object.image:
            self.object.processing_status = Receipt.STATUS_PENDING
            self.object.processing_error_code = Receipt.ERROR_CODE_NONE
            self.object.processing_error = ''
            self.object.extracted_text = ''
            self.object.save(update_fields=['processing_status', 'processing_error_code', 'processing_error', 'extracted_text'])

            try:
                process_receipt_ocr_task.delay(self.object.pk)
            except Exception as exc:
                self.object.processing_status = Receipt.STATUS_FAILED
                self.object.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
                self.object.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
                self.object.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])

        return response


class ReceiptListView(ListView):
    model = Receipt
    template_name = 'scanner/receipt_list.html'
    context_object_name = 'receipts'
    ordering = ['-uploaded_at']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['failed_count'] = Receipt.objects.filter(processing_status=Receipt.STATUS_FAILED).count()
        failed_by_code = (
            Receipt.objects
            .filter(processing_status=Receipt.STATUS_FAILED)
            .exclude(processing_error_code=Receipt.ERROR_CODE_NONE)
            .values('processing_error_code')
            .annotate(count=Count('id'))
            .order_by('-count')
        )
        context['failed_count_by_code'] = list(failed_by_code)
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
def receipt_retry_view(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)

    if not receipt.image:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_NO_IMAGE
        receipt.processing_error = 'No receipt image found'
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])
        return redirect('receipt-detail', pk=receipt.pk)

    receipt.processing_status = Receipt.STATUS_PENDING
    receipt.processing_error_code = Receipt.ERROR_CODE_NONE
    receipt.processing_error = ''
    receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])

    try:
        process_receipt_ocr_task.delay(receipt.pk)
    except Exception as exc:
        receipt.processing_status = Receipt.STATUS_FAILED
        receipt.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
        receipt.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])

    return redirect('receipt-detail', pk=receipt.pk)


@require_POST
def receipt_retry_failed_all_view(request):
    failed_receipts = Receipt.objects.filter(processing_status=Receipt.STATUS_FAILED).exclude(image='')

    for receipt in failed_receipts:
        receipt.processing_status = Receipt.STATUS_PENDING
        receipt.processing_error_code = Receipt.ERROR_CODE_NONE
        receipt.processing_error = ''
        receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])

        try:
            process_receipt_ocr_task.delay(receipt.pk)
        except Exception as exc:
            receipt.processing_status = Receipt.STATUS_FAILED
            receipt.processing_error_code = Receipt.ERROR_CODE_ENQUEUE_FAILED
            receipt.processing_error = f'Failed to enqueue OCR task: {str(exc)[:200]}'
            receipt.save(update_fields=['processing_status', 'processing_error_code', 'processing_error'])

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