from django.contrib import admin
from django.utils.safestring import mark_safe
from .models import Product, Variation, ReviewRating, ProductGallery
from .plant_descriptions import format_plant_help_text, PLANT_DESCRIPTIONS
import admin_thumbnails

# Register your models here.

@admin_thumbnails.thumbnail('image')
class ProductGalleryInline(admin.TabularInline):
    model = ProductGallery
    extra = 1

class ProductAdmin(admin.ModelAdmin):
    list_display = ('product_name', 'price', 'stock', 'category', 'modified_date', 'is_available')
    prepopulated_fields = {'slug': ('product_name',)}
    inlines = [ProductGalleryInline]
    
    def formfield_for_dbfield(self, db_field, **kwargs):
        field = super().formfield_for_dbfield(db_field, **kwargs)
        
        # Add plant care information as help text for description field
        if db_field.name == 'description':
            plant_help_texts = []
            for plant_key, plant_data in PLANT_DESCRIPTIONS.items():
                care_points_html = ''.join([f"<li>{point}</li>" for point in plant_data.get('care_points', [])])
                plant_help_text = f"""
                <div style='background-color: #000000; padding: 5px; border-radius: 5px; margin-bottom: 10px; line-height: 1.6;'>
                    <h4 style='margin-bottom: 10px;'>{plant_key.capitalize()}:</h4>
                    <ul style='margin-bottom: 0; padding-left: 20px;'>
                        {care_points_html}
                    </ul>
                </div>
                """
                plant_help_texts.append(plant_help_text)
            
            if plant_help_texts:
                field.help_text = mark_safe(
                    f"<div style='max-height: 300px; overflow-y: auto; border: 1px solid #ddd; padding: 10px;'>"
                    f"<h3 style='color: #27ae60; margin-bottom: 5px;'>Available Plant Care Information:</h3>"
                    f"{''.join(plant_help_texts)}"
                    f"</div>"
                )
        
        return field

class VariationAdmin(admin.ModelAdmin):
    list_display = ('product', 'variation_category', 'variation_value', 'is_active')
    list_editable = ('is_active',)
    list_filter = ('product', 'variation_category', 'variation_value',)

admin.site.register(Product, ProductAdmin)
admin.site.register(Variation, VariationAdmin)
admin.site.register(ReviewRating)
admin.site.register(ProductGallery)