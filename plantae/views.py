from django.shortcuts import render
from django.db.models import Sum
from store.models import Product
from django.utils import timezone
from datetime import timedelta

def home(request):
    #bestsellers
    bestsellers = Product.objects.annotate(
        total_sales=Sum('orderproduct__quantity')
    ).order_by('-total_sales', '-id')[:4]

    #new arrivals
    new_arrivals = Product.objects.filter(
        is_available=True
    ).order_by('-created_date')[:8]

    context = {
        'bestsellers': bestsellers,
        'new_arrivals': new_arrivals,
    }
    return render(request, 'home.html', context)