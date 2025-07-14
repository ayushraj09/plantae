# Carts App

## Purpose
Manages shopping cart functionality for users (both authenticated and guests) in the Plantae project.

## Main Features
- Add, remove, and update products in the cart.
- Handles product variations (color, size, etc.).
- Calculates cart totals, tax, and grand total.
- Checkout process integration.

## Key Models
- **Cart**: Represents a shopping cart (session-based for guests).
- **CartItem**: Items in the cart, linked to products, variations, and user/session.

## Key Views
- `add_cart`, `remove_cart`, `remove_cart_item`: Cart item management.
- `cart`: Displays cart contents and totals.
- `checkout`: Handles checkout page and calculations.

## Context Processors
- `counter`: Provides cart item count for display in the navbar.

## Admin
- Admin interface for cart and cart items.

## Notes
- Integrates with `store` for product and variation data.
- Handles both authenticated and guest users. 