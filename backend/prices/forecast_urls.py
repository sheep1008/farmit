from django.urls import path

from . import forecast_views, sell_now

urlpatterns = [
    path('forecasts', forecast_views.forecasts, name='forecasts'),
    path('forecasts/history', forecast_views.forecast_history, name='forecast-history'),
    path('recommendations',forecast_views.recommendations, name='recommendations'),
    path('recommendations/now', sell_now.sell_now, name='sell-now'),
]
