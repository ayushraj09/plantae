from django.db import models
from category.models import Category
from django.urls import reverse
from accounts.models import Account
from django.db.models import Avg, Count
from PIL import Image

# Create your models here.

class Product(models.Model):
    product_name = models.CharField(max_length=50, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    allowed_variations = models.CharField(
        max_length=100, 
        blank=True,
        help_text="Comma separated list of allowed variation types (e.g. color,size,pack)"
    )
    description = models.TextField(
        max_length=500, 
        blank=False,
        help_text="Product description. If this is a plant product, include the plant name to automatically display care information."
    )
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
    
    def averageRating(self):
        reviews = ReviewRating.objects.filter(product=self, status=True).aggregate(average=Avg('rating'))
        avg = 0
        if reviews['average'] is not None:
            avg = float(reviews['average'])
        return avg
    
    def countReview(self):
        reviews = ReviewRating.objects.filter(product=self, status=True).aggregate(count=Count('id'))
        count = 0
        if reviews['count'] is not None:
            count = int(reviews['count'])
        return count
    
    def get_allowed_variations(self):
        """Returns a queryset of Variation objects for this product that match allowed types"""
        if self.allowed_variations:
            allowed = [x.strip() for x in self.allowed_variations.split(",")]
            return Variation.objects.filter(product=self, variation_category__in=allowed, is_active=True)
        return Variation.objects.none()
    
    def get_plant_info(self):
        """Check if this product matches any plant in PLANT_DESCRIPTIONS and return plant info"""
        from .plant_descriptions import PLANT_DESCRIPTIONS
        
        product_name_lower = self.product_name.lower()
        
        # Check if the product name matches any plant in our descriptions
        for plant_key in PLANT_DESCRIPTIONS.keys():
            if plant_key.lower() in product_name_lower or product_name_lower in plant_key.lower():
                plant_info = PLANT_DESCRIPTIONS[plant_key].copy()
                plant_info['name'] = plant_key.capitalize()
                return plant_info
        return None
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.product_images:
            img = Image.open(self.product_images.path)
            max_size = 800
            if img.height > max_size or img.width > max_size:
                img.thumbnail((max_size, max_size))
                img.save(self.product_images.path)

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
    is_default = models.BooleanField(default=False)
    created_date = models.DateTimeField(auto_now_add=True)

    objects = VariationManager()

    def save(self, *args, **kwargs):
        if self.is_default:
            Variation.objects.filter(
                product=self.product,
                variation_category=self.variation_category,
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
        
    def __str__(self):
        return self.variation_value
    
class ReviewRating(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    user = models.ForeignKey(Account, on_delete=models.CASCADE)
    subject = models.CharField(max_length=100, blank=True)
    review = models.TextField(max_length=500, blank=True)
    rating = models.FloatField()
    ip = models.CharField(max_length=20, blank=True)
    status = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateField(auto_now=True)

    def __str__(self):
        return self.subject
    
class ProductGallery(models.Model):
    product = models.ForeignKey(Product, default=None, on_delete=models.CASCADE)
    image = models.ImageField(upload_to='store/products', max_length=255)

    def __str__(self):
        return self.product.product_name
    
    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.image:
            img = Image.open(self.image.path)
            max_size = 800
            if img.height > max_size or img.width > max_size:
                img.thumbnail((max_size, max_size))
                img.save(self.image.path)

    class Meta:
        verbose_name = 'productgallery'
        verbose_name_plural = 'Product gallery'