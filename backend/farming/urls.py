from django.urls import path

from . import views

urlpatterns = [
    path('monthly', views.monthly, name='farming-monthly'),
    path('calendar', views.calendar, name='farming-calendar'),
    path('summary', views.summary, name='farming-summary'),
    path('guide', views.guide, name='farming-guide'),
    path('search', views.search, name='farming-search'),
    path('glossary', views.glossary, name='farming-glossary'),
    path('diagnose', views.diagnose_view, name='farming-diagnose'),
]
