from django.urls import path

from . import views

urlpatterns = [
    path('realtime', views.realtime, name='prices-realtime'),
    path('daily', views.daily, name='prices-daily'),
    path('compare', views.compare, name='prices-compare'),
]
