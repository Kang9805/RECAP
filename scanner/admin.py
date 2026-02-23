from django.contrib import admin

from .models import Receipt, ReceiptItem


class ReceiptItemInline(admin.TabularInline):
    model = ReceiptItem
    extra = 0


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = ('id', 'uploaded_at')
    inlines = [ReceiptItemInline]


@admin.register(ReceiptItem)
class ReceiptItemAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'quantity', 'unit_price', 'receipt')
