from django.urls import path

from chat import views

urlpatterns = [
    path('messages', views.messages),
    path('sessions', views.sessions),
    path('sessions/<int:session_id>', views.session_detail),
]
