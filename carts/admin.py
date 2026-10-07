from django.contrib import admin
from .models import Cart, CartItem, Coupon
# Register your models here.

class CartAdmin(admin.ModelAdmin):
    list_display=('cart_id', 'date_added')

class CartItemAdmin(admin.ModelAdmin):
    list_display=('product', 'cart', 'quantity', 'is_active')

admin.site.register(Cart, CartAdmin)
admin.site.register(CartItem, CartItemAdmin)


@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = ('code', 'user', 'product', 'percent', 'max_units', 'expires_at', 'used_at', 'order', 'ticket')
    list_filter = ('used_at', 'expires_at')
    search_fields = ('code', 'user__email', 'product__product_name')
    raw_id_fields = ('user', 'product', 'order', 'ticket')
