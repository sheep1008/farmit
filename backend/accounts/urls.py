from django.urls import path

from . import sales_views, views

urlpatterns = [
    path('auth/csrf', views.csrf, name='csrf'),
    path('auth/check-username', views.check_username, name='check-username'),
    path('auth/signup', views.signup, name='signup'),
    path('auth/login', views.login_view, name='login'),
    path('auth/logout', views.logout_view, name='logout'),
    path('users/me', views.me, name='me'),
    path('sales', sales_views.sales, name='sales'),
    path('sales/<int:sale_id>', sales_views.sale_detail, name='sale-detail'),
]
