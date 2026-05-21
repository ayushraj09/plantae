from django.urls import path
from . import views

urlpatterns = [
    path('place_order/', views.place_order, name='place_order'),
    path('payments/', views.payments, name='payments'),
    path('razorpay/callback/', views.razorpay_callback, name='razorpay_callback'),
     path('order-success/<str:order_number>/<str:payment_id>/', views.order_success, name='order_success'),

] 
