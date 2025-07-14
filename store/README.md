# Store App

## Purpose
Manages products, product variations, reviews, and the main store interface for Plantae.

## Main Features
- Product listing, detail, and search.
- Product variations (color, size, pack).
- Product reviews and ratings.
- Product gallery images.
- Plant care information for products.
- Pagination and price filtering.

## Key Models
- **Product**: Main product model, linked to category.
- **Variation**: Product variations (color, size, pack).
- **ReviewRating**: User reviews and ratings for products.
- **ProductGallery**: Additional images for products.

## Key Views
- `store`: Product listing and filtering.
- `product_detail`: Product detail page with reviews and plant care info.
- `search`: Product search.
- `submit_review`: Submit or update a product review.

## Admin
- Admin interface for products, variations, reviews, and galleries.

## Notes
- Plant care info is shown for plant products.
- Integrates with `category` for product organization and filtering. 