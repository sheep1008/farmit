from django.urls import path

from . import forecast_views

urlpatterns = [
    path('forecasts', forecast_views.forecasts, name='forecasts'),
    path('recommendations', forecast_views.recommendations, name='recommendations'),
]
