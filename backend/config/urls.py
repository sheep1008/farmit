from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/prices/', include('prices.urls')),
    path('api/', include('codes.urls')),
    path('api/', include('api.urls')),
    path('api/', include('accounts.urls')),
    path('api/', include('alerts.urls')),
]
