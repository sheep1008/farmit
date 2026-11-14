from django.urls import path

from . import views

urlpatterns = [
    path('auth/csrf', views.csrf, name='csrf'),
    path('auth/check-username', views.check_username, name='check-username'),
    path('auth/signup', views.signup, name='signup'),
    path('auth/login', views.login_view, name='login'),
    path('auth/logout', views.logout_view, name='logout'),
    path('users/me', views.me, name='me'),
]
