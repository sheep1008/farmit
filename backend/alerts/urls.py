from django.urls import path

from . import case_views, views

urlpatterns = [
    path('cases', case_views.case_list, name='case-list'),
    path('alerts', views.alert_list, name='alert-list'),
    path('alerts/<int:alert_id>', views.alert_detail_view, name='alert-detail'),
    path('alerts/<int:alert_id>/read', views.alert_read, name='alert-read'),
]
