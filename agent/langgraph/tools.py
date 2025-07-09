from store.models import Product, Variation
from carts.models import CartItem
from django.contrib.auth import get_user_model
from langchain_core.tools import tool
from category.models import Category
from orders.models import Order, OrderProduct
from django.utils import timezone
from dateutil import parser as date_parser


@tool
def get_cart_items(user_id: int) -> str:
    """
    Get the products in the cart by using user id.
    """
    items = CartItem.objects.select_related('product').filter(user_id=user_id)
    if not items.exists():
        return "Your cart is empty."
    return "\n".join([f"{item.product.product_name} × {item.quantity}" for item in items])

@tool
def search_product(product_name: str = "", category_name: str = "") -> str:
    """
    Search for a product by name and/or category. Returns product information including ID and available variations.
    """
    try:
        products = Product.objects.all()
        if product_name:
            products = products.filter(product_name__icontains=product_name)
        if category_name:
            try:
                category = Category.objects.get(category_name__iexact=category_name)
                products = products.filter(category=category)
            except Category.DoesNotExist:
                return f"No category found with name '{category_name}'"
        if not products.exists():
            return f"No products found matching '{product_name}' in category '{category_name}'"
        result = []
        for product in products:
            result.append(f"Product ID: {product.id}, Name: {product.product_name}, Category: {product.category.category_name}")
        return "\n".join(result)
    except Exception as e:
        return f"Error searching for product: {str(e)}"

@tool
def add_to_cart(user_id: int, product_name: str, variation_dict: dict = None) -> str:
    """
    Add the product to the cart by product name. If there exists a variation in the product, first get the variations THEN ONLY add the product with variation in the cart. 
    If the product or product with certain variation already exists in the cart, increase the quantity of that product by 1.
    Now less sensitive: prefers exact match, else picks the first partial match, only asks for clarification if truly ambiguous.
    """
    if variation_dict is None:
        variation_dict = {}
    try:
        User = get_user_model()
        current_user = User.objects.get(id=user_id)
        
        # Search for product by name (case-insensitive, partial match)
        products = Product.objects.filter(product_name__icontains=product_name)
        if not products.exists():
            # Try to suggest similar products
            similar_products = Product.objects.filter(product_name__icontains=product_name.split()[0])
            if similar_products.exists():
                names = ", ".join([p.product_name for p in similar_products[:5]])
                return (
                    f"No product found with name '{product_name}'. "
                    f"Did you mean: {names}? Please specify the exact product name."
                )
            return (
                f"No product found with name '{product_name}'. "
                "Would you like to see the available options or try adding a different plant?"
            )
        
        # Prefer exact match if available
        exact_matches = products.filter(product_name__iexact=product_name)
        if exact_matches.exists():
            product = exact_matches.first()
        elif products.count() == 1:
            product = products.first()
        else:
            product = products.first()
            similar_names = ", ".join([p.product_name for p in products[:5]])
            return (
                f"Multiple products found matching '{product_name}': {similar_names}. "
                f"Adding '{product.product_name}' to your cart. If this is not correct, please specify the exact product name."
            )
        
        product_variation = []
        # Extract variations
        for key, value in variation_dict.items():
            try:
                variation = Variation.objects.get(
                    product=product,
                    variation_category__iexact=key,
                    variation_value__iexact=value
                )
                product_variation.append(variation)
            except Variation.DoesNotExist:
                continue
        cart_items = CartItem.objects.filter(product=product, user=current_user)
        for item in cart_items:
            existing_variation = list(item.variation.all())
            if set(existing_variation) == set(product_variation):
                item.quantity += 1
                item.save()
                return f"Increased quantity of {product.product_name} with selected variations."
        # If no matching variation, create new item
        new_item = CartItem.objects.create(product=product, quantity=1, user=current_user)
        if product_variation:
            new_item.variation.set(product_variation)
        new_item.save()
        return f"Added {product.product_name} to cart."
    except User.DoesNotExist:
        return "User not found."
    except Exception as e:
        return f"Error: {str(e)}"
    
@tool
def remove_cart_item(user_id: int, product_name: str) -> str:
    """
    Remove a product from the cart by product name.
    Gets cart items, searches for the product name, and removes the matching item.
    """
    try:
        User = get_user_model()
        current_user = User.objects.get(id=user_id)
        
        # Get cart items for the user
        cart_items = CartItem.objects.select_related('product').filter(user=current_user)
        if not cart_items.exists():
            return "Your cart is empty."
        
        # Search for the product in cart items
        matching_items = []
        for item in cart_items:
            if product_name.lower() in item.product.product_name.lower():
                matching_items.append(item)
        
        if not matching_items:
            return f"No product found in cart with name '{product_name}'."
        
        # Remove all matching items
        removed_count = 0
        removed_names = []
        
        for item in matching_items:
            removed_names.append(item.product.product_name)
            item.delete()
            removed_count += 1
        
        if removed_count == 1:
            return f"Removed {removed_names[0]} from your cart."
        else:
            return f"Removed {removed_count} items from your cart: {', '.join(removed_names)}"
        
    except User.DoesNotExist:
        return "User not found."
    except Exception as e:
        return f"Error removing item from cart: {str(e)}"

@tool
def get_checkout_url(user_id: int) -> str:
    """
    Returns the URL for the checkout page.
    """
    return "You can checkout your order here: https://plantae.live/cart/checkout/"

@tool
def get_my_orders_url(user_id: int) -> str:
    """
    Returns the URL for the user's orders page.
    """
    return "You can view all your orders here: https://plantae.live/accounts/my_orders/"

@tool
def get_order_details_by_id(user_id: int, order_id: str) -> str:
    """
    Retrieve order details (status, products, date, total) for a given order ID and user.
    """
    try:
        order = Order.objects.get(user_id=user_id, order_number=order_id)
        products = OrderProduct.objects.filter(order=order)
        product_list = "\n".join([
            f"- {item.product.product_name} × {item.quantity}" for item in products
        ])
        details = (
            f"Order ID: {order.order_number}\n"
            f"Status: {order.status}\n"
            f"Date: {order.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Total: ₹{order.order_total}\n"
            f"Products:\n{product_list}"
        )
        return details
    except Order.DoesNotExist:
        return f"No order found with ID {order_id}."
    except Exception as e:
        return f"Error retrieving order details: {str(e)}"

@tool
def get_orders_by_date(user_id: int, user_date_str: str) -> str:
    """
    Retrieve all orders for a user on a specific date (YYYY-MM-DD).
    """
    try:
        user_date = date_parser.parse(user_date_str, fuzzy=True).date()
    except Exception:
        return "Sorry, I couldn't understand the date you mentioned."

    # Fetch all orders for the user
    orders = Order.objects.filter(user_id=user_id)
    # Find orders matching the date
    matching_orders = [order for order in orders if order.created_at.date() == user_date]
    if not matching_orders:
        return f"There is no order recorded for {user_date_str}."
    # Format and return the order(s)
    result = []
    for order in matching_orders:
        products = OrderProduct.objects.filter(order=order)
        product_list = ", ".join([f"{item.product.product_name} × {item.quantity}" for item in products])
        result.append(
            f"Order ID: {order.order_number}, Status: {order.status}, Total: ₹{order.order_total}, Products: {product_list}"
        )
    return "\n".join(result)

@tool
def get_most_recent_order(user_id: int) -> str:
    """
    Retrieve the most recent order for a user, including order details and products.
    """
    try:
        order = Order.objects.filter(user_id=user_id).order_by('-created_at').first()
        if not order:
            return "No recent orders found."
        products = OrderProduct.objects.filter(order=order)
        product_list = ", ".join([f"{item.product.product_name} × {item.quantity}" for item in products])
        details = (
            f"Order ID: {order.order_number}\n"
            f"Status: {order.status}\n"
            f"Date: {order.created_at.strftime('%Y-%m-%d %I:%M %p')}\n"
            f"Total: ₹{order.order_total}\n"
            f"Products: {product_list}"
        )
        return details
    except Exception as e:
        return f"Error retrieving most recent order: {str(e)}"
