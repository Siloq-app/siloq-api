from django.urls import path
from . import views

urlpatterns = [
    path('generate/', views.generate_plan, name='ai-generate'),
]
