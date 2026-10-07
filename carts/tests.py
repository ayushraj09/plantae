import io
import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from accounts.models import Account
from carts.models import CartItem, Coupon
from carts.pricing import price_cart
from category.models import Category
from orders.models import Order
from store.models import Product


def tiny_image(name):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


def make_user(name, email):
    user = Account.objects.create_user(name, "Test", name.lower(), email, "pw", phone_number="9000000000")
    user.is_active = True
    user.save()
    return user


class CouponTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)

        cat = Category.objects.create(category_name="Plants", slug="plants")
        self.rose = Product.objects.create(product_name="Rose", slug="rose", price=400, stock=50, category=cat,
                                           description="x", product_images=tiny_image("rose.png"))
        self.jade = Product.objects.create(product_name="Jade", slug="jade", price=100, stock=50, category=cat,
                                           description="x", product_images=tiny_image("jade.png"))
        self.owner = make_user("Asha", "asha@example.com")
        self.other = make_user("Ravi", "ravi@example.com")
        self.coupon = Coupon.objects.create(code="ROSE10", user=self.owner, product=self.rose, percent=10,
                                            max_units=2, expires_at=timezone.now() + timedelta(days=7))

    def cart(self, user, **quantities):
        for product, qty in quantities.items():
            CartItem.objects.create(user=user, product=getattr(self, product), quantity=qty)
        return CartItem.objects.filter(user=user)

    # --- pricing -----------------------------------------------------------
    def test_discount_only_on_coupon_product_and_capped_at_two_units(self):
        pricing = price_cart(self.cart(self.owner, rose=3, jade=1), self.coupon)
        self.assertEqual(pricing.total, Decimal("1300.00"))      # 3*400 + 100
        self.assertEqual(pricing.discount, Decimal("80.00"))     # 10% of 2 roses only
        self.assertEqual(pricing.tax, Decimal("219.60"))         # 18% of 1220
        self.assertEqual(pricing.grand_total, Decimal("1439.60"))

    def test_no_discount_without_coupon_product_in_cart(self):
        pricing = price_cart(self.cart(self.owner, jade=2), self.coupon)
        self.assertEqual(pricing.discount, Decimal("0.00"))
        self.assertIsNone(pricing.coupon)

    # --- who can use it ----------------------------------------------------
    def apply(self, user, code):
        self.client.force_login(user)
        return self.client.post(reverse("apply_coupon"), {"coupon_code": code, "next": reverse("cart")}, follow=True)

    def test_owner_can_apply_and_cart_shows_discount(self):
        self.cart(self.owner, rose=1)
        resp = self.apply(self.owner, "rose10")  # case-insensitive
        self.assertContains(resp, "Coupon ROSE10 applied")
        self.assertEqual(resp.context["discount"], Decimal("40.00"))
        self.assertEqual(self.client.session.get("coupon_code"), "ROSE10")

    def test_other_user_cannot_use_someone_elses_code(self):
        self.cart(self.other, rose=1)
        resp = self.apply(self.other, "ROSE10")
        self.assertContains(resp, "valid for your account")
        self.assertIsNone(self.client.session.get("coupon_code"))
        self.assertEqual(resp.context["discount"], Decimal("0.00"))

    def test_session_cannot_carry_a_coupon_to_another_account(self):
        self.cart(self.other, rose=1)
        self.client.force_login(self.other)
        session = self.client.session
        session["coupon_code"] = "ROSE10"  # e.g. copied session
        session.save()
        resp = self.client.get(reverse("cart"))
        self.assertEqual(resp.context["discount"], Decimal("0.00"))

    def test_two_users_can_hold_the_same_code_independently(self):
        theirs = Coupon.objects.create(code="ROSE10", user=self.other, product=self.rose, percent=20,
                                       max_units=2, expires_at=timezone.now() + timedelta(days=7))
        self.cart(self.other, rose=1)
        resp = self.apply(self.other, "ROSE10")
        self.assertEqual(resp.context["coupon"], theirs)
        self.assertEqual(resp.context["discount"], Decimal("80.00"))

    def test_expired_used_and_wrong_product_are_rejected(self):
        self.cart(self.owner, jade=1)
        self.assertContains(self.apply(self.owner, "ROSE10"), "only applies to Rose")
        self.cart(self.owner, rose=1)
        Coupon.objects.filter(pk=self.coupon.pk).update(expires_at=timezone.now() - timedelta(minutes=1))
        self.assertContains(self.apply(self.owner, "ROSE10"), "expired")
        Coupon.objects.filter(pk=self.coupon.pk).update(expires_at=timezone.now() + timedelta(days=1),
                                                        used_at=timezone.now())
        self.assertContains(self.apply(self.owner, "ROSE10"), "already been used")

    # --- full checkout -----------------------------------------------------
    @mock.patch("orders.views.razorpay.Client")
    def test_checkout_charges_discounted_amount_and_consumes_coupon_once(self, client_cls):
        client_cls.return_value.order.create.return_value = {"id": "order_TEST1"}
        self.cart(self.owner, rose=3)
        self.apply(self.owner, "ROSE10")
        self.assertContains(self.client.get(reverse("checkout")), "Coupon ROSE10")

        form = {"first_name": "Asha", "last_name": "Test", "phone": "9000000000", "email": "asha@example.com",
                "address_line_1": "1 St", "address_line_2": "-", "pin_code": "560001", "city": "BLR",
                "state": "KA", "country": "IN", "order_note": ""}
        self.client.post(reverse("place_order"), form)
        resp = self.client.get(reverse("payments"))
        # 3*400 = 1200, minus 80 = 1120, plus 18% = 1321.60 -> paise
        client_cls.return_value.order.create.assert_called_once()
        self.assertEqual(client_cls.return_value.order.create.call_args.kwargs["data"]["amount"], 132160)
        self.assertEqual(resp.context["discount"], Decimal("80.00"))
        order = Order.objects.get(razorpay_order_id="order_TEST1")
        self.assertEqual((order.coupon_code, order.discount, order.order_total), ("ROSE10", 80.0, 1321.6))

        # Payment succeeds -> coupon consumed and linked to the order
        self.client.post(reverse("razorpay_callback"), {"razorpay_payment_id": "pay_1", "razorpay_order_id": "order_TEST1",
                                                        "razorpay_signature": "sig"})
        self.coupon.refresh_from_db()
        self.assertIsNotNone(self.coupon.used_at)
        self.assertEqual(self.coupon.order, order)
        self.assertIsNone(self.client.session.get("coupon_code"))

        # It can't be used again
        self.cart(self.owner, rose=1)
        self.assertContains(self.apply(self.owner, "ROSE10"), "already been used")
