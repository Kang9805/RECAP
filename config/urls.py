"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from scanner.views import (
    ReceiptUploadView,
    ReceiptListView,
    ReceiptDetailView,
    SignupView,
    receipt_status_api_view,
    receipt_delete_view,
    receipt_delete_selected_view,
    receipt_retry_view,
    receipt_retry_failed_all_view,
    receipt_item_create_view,
    receipt_item_update_view,
    receipt_item_delete_view,
)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('accounts/signup/', SignupView.as_view(), name='signup'),
    path('', ReceiptListView.as_view(), name='receipt-list'),
    path('receipts/upload/', ReceiptUploadView.as_view(), name='receipt-upload'),
    path('receipts/<int:pk>/', ReceiptDetailView.as_view(), name='receipt-detail'),
    path('receipts/<int:pk>/status/', receipt_status_api_view, name='receipt-status-api'),
    path('receipts/<int:pk>/delete/', receipt_delete_view, name='receipt-delete'),
    path('receipts/delete-selected/', receipt_delete_selected_view, name='receipt-delete-selected'),
    path('receipts/<int:pk>/retry/', receipt_retry_view, name='receipt-retry'),
    path('receipts/retry-failed-all/', receipt_retry_failed_all_view, name='receipt-retry-failed-all'),
    path('receipts/<int:receipt_pk>/items/create/', receipt_item_create_view, name='receipt-item-create'),
    path('receipts/<int:receipt_pk>/items/<int:item_pk>/update/', receipt_item_update_view, name='receipt-item-update'),
    path('receipts/<int:receipt_pk>/items/<int:item_pk>/delete/', receipt_item_delete_view, name='receipt-item-delete'),
]

# media 파일은 DEBUG 여부와 관계없이 Django가 직접 제공
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
