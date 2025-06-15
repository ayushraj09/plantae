from django.db import models
from category.models import Category
from django.urls import reverse

# Create your models here.
class Product(models.Model):
    product_name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    allowed_variations = models.CharField(max_length=100, blank=True,
        help_text="Comma separated list of allowed variation types (e.g. color,size)")
    description = models.TextField(max_length=500, blank=False)
    price = models.DecimalField(max_digits=7, decimal_places=2)
    product_images = models.ImageField(upload_to='media/product')
    stock = models.IntegerField()
    is_available = models.BooleanField(default=True)
    category = models.ForeignKey(Category, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    modified_date = models.DateTimeField(auto_now=True)
    
    def get_url(self):
        return reverse('product_detail', args=[self.category.slug, self.slug])

    def __str__(self):
        return self.product_name
    
    def get_allowed_variations(self):
        # Returns a queryset of Variation objects for this product that match allowed types
        if self.allowed_variations:
            allowed = [x.strip() for x in self.allowed_variations.split(",")]
            return Variation.objects.filter(product=self, variation_category__in=allowed, is_active=True)
        return Variation.objects.none()
    
class VariationManager(models.Manager):
    def colors(self):
        return super(VariationManager, self).filter(variation_category='color', is_active=True)
    
    def sizes(self):
        return super(VariationManager, self).filter(variation_category='size', is_active=True)



variation_category_choice = (
    ('color', 'color'),
    ('size', 'size'),
    ('pack', 'pack')
)

class Variation(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    variation_category = models.CharField(max_length=100, choices=variation_category_choice)
    variation_value = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    objects = VariationManager()

    def __str__(self):
        return self.variation_value