from django.urls import path

from . import forecast_views, sell_now

urlpatterns = [
    path('forecasts', forecast_views.forecasts, name='forecasts'),
    path('recommendations', forecast_views.recommendations, name='recommendations'),
    path('recommendations/now', sell_now.sell_now, name='sell-now'),
]
