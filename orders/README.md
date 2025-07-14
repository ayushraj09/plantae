# Orders App

## Purpose
Handles order placement, payment, and order history for the Plantae platform.

## Main Features
- Place orders from cart items.
- Integrates with Razorpay for payments.
- Stores order details, shipping address, and payment info.
- Order status tracking (Accepted, Shipped, Delivered, Cancelled).
- Order history and order detail views for users.
- Sends order confirmation emails.

## Key Models
- **Order**: Stores order details and status.
- **OrderProduct**: Products in an order, with variations and quantity.
- **Payment**: Payment details for an order.

## Key Views
- `place_order`: Handles order creation.
- `payments`: Payment processing and confirmation.
- `order_success`: Order success page.
- `razorpay_callback`: Handles payment gateway callbacks.

## Admin
- Admin interface for orders, order products, and payments.

## Notes
- Integrates with `carts` and `store` for cart and product data.
- Sends email notifications on order placement. 