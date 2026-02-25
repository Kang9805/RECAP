from django.shortcuts import render, redirect
from django.views.generic import CreateView, ListView, DetailView
from django.urls import reverse_lazy
from .models import Receipt, ReceiptItem
from .services.ocr import extract_text_from_receipt


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