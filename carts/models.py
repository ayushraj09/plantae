from django.db import models
from store.models import Product, Variation
from accounts.models import Account

# Create your models here.
class Cart(models.Model):
    cart_id = models.CharField(max_length=250, blank=True)
    date_added = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.cart_id
    
class CartItem(models.Model):
    user = models.ForeignKey(Account, on_delete=models.CASCADE, null=True)
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variation = models.ManyToManyField(Variation, blank=True)
    cart = models.ForeignKey(Cart, models.CASCADE, null=True)
    quantity = models.IntegerField()
    is_active = models.BooleanField(default = True)

    def sub_total(self):
        return self.product.price * self.quantity

    def __unicode__(self):
        return self.product

class Coupon(models.Model):
    """A user-specific discount code for one product (created when staff approve a price match).

    Applies to at most ``max_units`` units of ``product`` in a single order, until
    ``expires_at``; it is consumed (``used_at``) only once payment succeeds.
    """
    code = models.CharField(max_length=40)
    user = models.ForeignKey(Account, on_delete=models.CASCADE, related_name='coupons')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='coupons')
    percent = models.PositiveSmallIntegerField()
    max_units = models.PositiveSmallIntegerField(default=2)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    order = models.ForeignKey('orders.Order', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    ticket = models.ForeignKey('agent.EscalationTicket', on_delete=models.SET_NULL, null=True, blank=True, related_name='coupons')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at',)
        constraints = [models.UniqueConstraint(fields=['user', 'code'], name='unique_coupon_code_per_user')]

    def __str__(self):
        return f"{self.code} ({self.percent}% off {self.product}) for {self.user}"
