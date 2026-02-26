from django.shortcuts import get_object_or_404, redirect
from django.views.decorators.http import require_POST
from django.views.generic import CreateView, ListView, DetailView
from django.urls import reverse_lazy
from .models import Receipt, ReceiptItem
from .services.ocr import extract_text_from_receipt
from .services.parser import parse_receipt_items


class ReceiptUploadView(CreateView):
    model = Receipt
    fields = ['image']
    template_name = 'scanner/receipt_form.html'
    success_url = reverse_lazy('receipt-list')
    
    def form_valid(self, form):
        response = super().form_valid(form)
        # OCR 실행
        if self.object.image:
            text = extract_text_from_receipt(self.object.image.path)
            self.object.extracted_text = text
            self.object.save()

            parsed_items = parse_receipt_items(text)
            receipt_items = [
                ReceiptItem(
                    receipt=self.object,
                    name=item['name'],
                    quantity=item['quantity'],
                    unit_price=item['unit_price'],
                )
                for item in parsed_items
            ]

            if receipt_items:
                ReceiptItem.objects.bulk_create(receipt_items)

        return response


class ReceiptListView(ListView):
    model = Receipt
    template_name = 'scanner/receipt_list.html'
    context_object_name = 'receipts'
    ordering = ['-uploaded_at']


class ReceiptDetailView(DetailView):
    model = Receipt
    template_name = 'scanner/receipt_detail.html'
    context_object_name = 'receipt'


@require_POST
def receipt_delete_view(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    receipt.delete()
    return redirect('receipt-list')