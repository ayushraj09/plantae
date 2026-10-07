from store.models import Product, Variation
from carts.models import CartItem
from django.contrib.auth import get_user_model
from langchain_core.tools import tool
from category.models import Category
from orders.models import Order, OrderProduct
from dateutil import parser as date_parser
from django.conf import settings
import difflib
import re

MAX_CART_QUANTITY = 50


def find_product(name: str):
    """Match a user-supplied product name ("Rose plant", "snake plnt") to the catalog."""
    name = (name or "").strip()
    if not name:
        return None
    product = (Product.objects.filter(product_name__iexact=name).first()
               or Product.objects.filter(product_name__icontains=name).first())
    if product:
        return product
    catalog = list(Product.objects.values_list("product_name", flat=True))
    # Catalog name inside the user's words ("Rose" in "Rose plant"); prefer the longest.
    contained = sorted((n for n in catalog if re.search(rf"\b{re.escape(n.lower())}\b", name.lower())), key=len, reverse=True)
    best = contained[0] if contained else next(iter(difflib.get_close_matches(name, catalog, n=1, cutoff=0.6)), None)
    return Product.objects.filter(product_name=best).first() if best else None


def resolve_product(product_name: str):
    """Return (product, None), or (None, message for the user) when it is missing or ambiguous."""
    name = (product_name or "").strip()
    products = Product.objects.filter(product_name__icontains=name)
    exact = products.filter(product_name__iexact=name).first()
    if exact:
        return exact, None
    if products.count() == 1:
        return products.first(), None
    if products.count() > 1:
        names = ", ".join(p.product_name for p in products[:5])
        return None, (f"Multiple products match '{product_name}': {names}. "
                      "Nothing was added yet. Please tell me which one you'd like.")
    product = find_product(name)
    if product:
        return product, None
    return None, (f"No product found with name '{product_name}'. "
                  "Would you like to see the available options or try a different plant?")

def extract_user_id(user_id) -> int:
    """
    Helper function to extract user_id from either int or enhanced string format.
    Returns user_id as int or raises ValueError.
    """
    if isinstance(user_id, int):
        return user_id
    elif isinstance(user_id, str) and user_id.startswith("User ID:"):
        try:
            return int(user_id.split(".")[0].split(":")[1].strip())
        except (ValueError, IndexError):
            raise ValueError("Invalid user ID format")
    else:
        raise ValueError("Invalid user ID type")

@tool
def get_cart_items(user_id: int) -> str:
    """
    Get the products in the cart by using user id.
    """
    try:
        user_id = extract_user_id(user_id)
        items = CartItem.objects.select_related('product').filter(user_id=user_id)
        if not items.exists():
            return "Your cart is empty."
        return "\n".join([f"{item.product.product_name} × {item.quantity}" for item in items])
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error retrieving cart items: {str(e)}"

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
def recommend_products_for_plant(plant_name: str, user_query: str = "") -> str:
    """
    Recommend products from the database that would be suitable for a specific plant.
    This tool searches for fertilizers, plant care products, and similar plants based on the identified plant.
    """
    try:
        plant_name = plant_name.lower().strip()
        user_query = user_query.lower().strip()
        
        # Search for products that might be suitable for this plant
        recommended_products = []
        
        # First, look for fertilizers and plant care products
        if any(word in user_query for word in ['fertilizer', 'fertiliser', 'nutrient', 'feed', 'care']):
            care_products = Product.objects.filter(
                category__category_name__in=['Plant Care', 'Fertilizer'],
                is_available=True
            )
            for product in care_products:
                recommended_products.append(f"🌱 {product.product_name} - {product.description[:100]}... (₹{product.price})")
        
        # Look for similar plants (same category or similar names)
        similar_plants = Product.objects.filter(
            product_name__icontains=plant_name,
            is_available=True
        )
        for product in similar_plants:
            recommended_products.append(f"🌿 {product.product_name} - {product.description[:100]}... (₹{product.price})")
        
        # If no direct matches, look for general plant care products
        if not recommended_products:
            general_care = Product.objects.filter(
                category__category_name__in=['Plant Care', 'Fertilizer'],
                is_available=True
            )[:5]  # Limit to 5 products
            for product in general_care:
                recommended_products.append(f"🌱 {product.product_name} - {product.description[:100]}... (₹{product.price})")
        
        if recommended_products:
            result = f"Here are some products that would be great for your {plant_name}:\n\n"
            result += "\n".join(recommended_products)
            result += f"\n\nYou can add any of these to your cart by saying 'Add [product name]'!"
            return result
        else:
            return f"I couldn't find specific products for {plant_name}, but you can browse our plant care and fertilizer categories for general care products."
            
    except Exception as e:
        return f"Error recommending products: {str(e)}"

@tool
def add_to_cart(user_id: int, product_name: str, variation_dict: dict = None, quantity: int = 1) -> str:
    """
    Add the product to the cart by product name. If there exists a variation in the product, first get the variations THEN ONLY add the product with variation in the cart. 
    quantity is how many the user asked for (default 1). If the product with the same variation is already in the cart, its quantity is increased by that amount.
    Prefers an exact name match, else a single partial match; asks the user to choose when several products match.
    Enforces that all required variations are specified if the product has variations.
    """
    try:
        user_id = extract_user_id(user_id)
        if variation_dict is None:
            variation_dict = {}
        try:
            quantity = max(1, min(int(quantity or 1), MAX_CART_QUANTITY))
        except (TypeError, ValueError):
            quantity = 1
        # Normalize keys to match required variations (case-insensitive)
        orig_variation_dict = variation_dict.copy()
        User = get_user_model()
        current_user = User.objects.get(id=user_id)
        product, problem = resolve_product(product_name)
        if problem:
            return problem
        # Check if product requires variations
        allowed = product.allowed_variations
        required_variations = []
        if allowed:
            allowed_types = [x.strip() for x in allowed.split(",") if x.strip()]
            if allowed_types:
                # Check if there is at least one active variation for this product
                has_variations = Variation.objects.filter(product=product, variation_category__in=allowed_types, is_active=True).exists()
                if has_variations:
                    required_variations = allowed_types
        # --- PATCH: Normalize user keys to match required_variations (case-insensitive) ---
        norm_variation_dict = {}
        for req in required_variations:
            for user_key in variation_dict:
                if user_key.lower() == req.lower():
                    norm_variation_dict[req] = variation_dict[user_key]
        # If user sent extra keys, keep them too (for robustness)
        for user_key in variation_dict:
            if user_key not in norm_variation_dict and user_key not in required_variations:
                norm_variation_dict[user_key] = variation_dict[user_key]
        variation_dict = norm_variation_dict
        # --- END PATCH ---
        # If required variations exist, check if all are present in variation_dict
        missing = [v for v in required_variations if v not in variation_dict or not variation_dict[v]]
        if missing:
            return f"Please specify the following required variation(s) for '{product.product_name}': {', '.join(missing)}."
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
                item.quantity += quantity
                item.save()
                return f"Added {quantity} more {product.product_name} to your cart (now {item.quantity})."
        # If no matching variation, create new item
        new_item = CartItem.objects.create(product=product, quantity=quantity, user=current_user)
        if product_variation:
            new_item.variation.set(product_variation)
        new_item.save()
        return f"Added {quantity} × {product.product_name} to cart."
    except ValueError as e:
        return f"Error: {str(e)}"
    except User.DoesNotExist:
        return "User not found."
    except Exception as e:
        return f"Error adding to cart: {str(e)}"
    
@tool
def remove_cart_item(user_id: int, product_name: str) -> str:
    """
    Remove a product from the cart by product name.
    Gets cart items, searches for the product name, and removes the matching item.
    """
    try:
        user_id = extract_user_id(user_id)
        User = get_user_model()
        current_user = User.objects.get(id=user_id)
        
        # Get cart items for the user
        cart_items = CartItem.objects.select_related('product').filter(user=current_user)
        if not cart_items.exists():
            return "Your cart is empty."
        
        # Prefer exact name matches; fall back to partial matches only if they
        # all refer to the same product (e.g. two variations of it).
        wanted = product_name.lower().strip()
        matching_items = [item for item in cart_items if item.product.product_name.lower() == wanted]
        if not matching_items:
            matching_items = [item for item in cart_items if wanted in item.product.product_name.lower()]
        
        if not matching_items:
            return f"No product found in cart with name '{product_name}'."
        matched_products = {item.product.product_name for item in matching_items}
        if len(matched_products) > 1:
            return (
                f"Several products in your cart match '{product_name}': {', '.join(sorted(matched_products))}. "
                "Nothing was removed. Please tell me which one to remove."
            )
        
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
        
    except ValueError as e:
        return f"Error: {str(e)}"
    except User.DoesNotExist:
        return "User not found."
    except Exception as e:
        return f"Error removing item from cart: {str(e)}"

@tool
def get_checkout_url(user_id: int) -> str:
    """
    Returns the URL for the checkout page.
    """
    return f"You can checkout your order here: {settings.SITE_URL.rstrip('/')}/cart/checkout/"

@tool
def get_my_orders_url(user_id: int) -> str:
    """
    Returns the URL for the user's orders page.
    """
    return f"You can view all your orders here: {settings.SITE_URL.rstrip('/')}/accounts/my_orders/"

@tool
def get_order_details_by_id(user_id: int, order_id: str) -> str:
    """
    Retrieve order details (status, products, date, total) for a given order ID and user.
    """
    try:
        user_id = extract_user_id(user_id)
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
    except ValueError as e:
        return f"Error: {str(e)}"
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
        user_id = extract_user_id(user_id)
        user_date = date_parser.parse(user_date_str, fuzzy=True).date()

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
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception:
        return "Sorry, I couldn't understand the date you mentioned."

@tool
def get_most_recent_order(user_id: int) -> str:
    """
    Retrieve the most recent order for a user, including order details and products.
    """
    try:
        user_id = extract_user_id(user_id)
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
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error retrieving most recent order: {str(e)}"

@tool
def list_product_variations(product_name: str) -> str:
    """
    List all available variation categories and values for a given product name.
    """
    try:
        product, problem = resolve_product(product_name)
        if problem:
            return problem
        allowed = product.allowed_variations
        if not allowed:
            return f"'{product.product_name}' does not have any selectable variations."
        allowed_types = [x.strip() for x in allowed.split(",") if x.strip()]
        if not allowed_types:
            return f"'{product.product_name}' does not have any selectable variations."
        result = [f"Available variations for '{product.product_name}':"]
        for var_type in allowed_types:
            values = Variation.objects.filter(product=product, variation_category__iexact=var_type, is_active=True).values_list('variation_value', flat=True).distinct()
            if values:
                result.append(f"- {var_type.capitalize()}: {', '.join(sorted(set(values)))}")
        if len(result) == 1:
            return f"No active variations found for '{product.product_name}'."
        return "\n".join(result)
    except Exception as e:
        return f"Error listing variations: {str(e)}"