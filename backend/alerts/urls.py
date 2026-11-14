from django.urls import path

from . import views

urlpatterns = [
    path('alerts', views.alert_list, name='alert-list'),
    path('alerts/<int:alert_id>', views.alert_detail_view, name='alert-detail'),
    path('alerts/<int:alert_id>/read', views.alert_read, name='alert-read'),
]
