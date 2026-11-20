from django.contrib import admin
from django.urls import include, path

handler404 = 'api.exceptions.not_found_handler'    # 주소 오타·잘못된 경로 값도 JSON 오류 모양으로
handler500 = 'api.exceptions.server_error_handler'

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/prices/', include('prices.urls')),
    path('api/', include('prices.forecast_urls')),
    path('api/', include('codes.urls')),
    path('api/', include('api.urls')),
    path('api/', include('accounts.urls')),
    path('api/', include('alerts.urls')),
    path('api/chat/', include('chat.urls')),
    path('api/farming/', include('farming.urls')),
    path('api/weather/', include('weather.urls')),
]
