import html
import io
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from PIL import Image

from category.models import Category
from store.models import Product


def tiny_image(name):
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "green").save(buf, format="PNG")
    return SimpleUploadedFile(name, buf.getvalue(), content_type="image/png")


class StoreListingTests(TestCase):
    def setUp(self):
        media = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media, ignore_errors=True)
        override = override_settings(MEDIA_ROOT=media)
        override.enable()
        self.addCleanup(override.disable)
        self.plants = Category.objects.create(category_name="Plants", slug="plants")
        seeds = Category.objects.create(category_name="Seeds", slug="seeds")
        for i in range(13):
            Product.objects.create(product_name=f"Plant {i:02d}", slug=f"plant-{i:02d}", price=100 + i * 10,
                                   stock=5, category=self.plants, description="x",
                                   product_images=tiny_image(f"p{i}.png"))
        Product.objects.create(product_name="Maize Seeds", slug="maize-seeds", price=240, stock=5,
                               category=seeds, description="x", product_images=tiny_image("seeds.png"))

    def test_item_count_wording(self):
        resp = self.client.get(reverse("products_by_category", args=["seeds"]))
        self.assertContains(resp, "1 item found")
        self.assertNotContains(resp, "1 items found")
        resp = self.client.get(reverse("products_by_category", args=["plants"]))
        self.assertContains(resp, "13 items found")

    def test_pagination_keeps_price_filter(self):
        resp = self.client.get(reverse("products_by_category", args=["plants"]), {"min_price": 0, "max_price": 500})
        self.assertIn('href="?min_price=0&max_price=500&page=2"', html.unescape(resp.content.decode()))
        page2 = self.client.get(reverse("products_by_category", args=["plants"]),
                                {"min_price": 0, "max_price": 200, "page": 2})
        # 0-200 matches Plant 00..10 (11 products) -> fits on page 1, page 2 clamps to last page
        self.assertEqual(page2.context["product_count"], 11)

    def test_reversed_price_range_is_swapped(self):
        resp = self.client.get(reverse("products_by_category", args=["plants"]), {"min_price": 150, "max_price": 100})
        self.assertEqual((resp.context["min_price"], resp.context["max_price"]), (100, 150))
        self.assertEqual(resp.context["product_count"], 6)  # 100, 110, ..., 150

    def test_category_pages_are_ordered(self):
        resp = self.client.get(reverse("products_by_category", args=["plants"]))
        names = [p.product_name for p in resp.context["products"]]
        self.assertEqual(names, sorted(names))
        self.assertEqual(len(names), 12)
