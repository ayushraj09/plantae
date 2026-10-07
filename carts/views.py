from django.shortcuts import render, redirect, get_object_or_404
from .models import Cart, CartItem
from store.models import Product, Variation
from django.core.exceptions import ObjectDoesNotExist
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .pricing import SESSION_KEY, check_coupon, find_coupon, price_cart, pricing_context, session_coupon
# Create your views here.

# This is a private function
def _cart_id(request):
    cart = request.session.session_key
    if not cart:
        cart = request.session.create()
    return cart

def add_cart(request, product_id):
    current_user = request.user
    product = Product.objects.get(id=product_id)
    # No legacy variation checks here
    if current_user.is_authenticated:
        product_variation = []
        if request.method == 'POST':
            for item in request.POST:
                key = item
                value = request.POST[key]
                try:
                    variation = Variation.objects.get(product=product, variation_category__iexact=key, variation_value__iexact=value)
                    product_variation.append(variation)
                except:
                    pass
        is_cart_item_exist = CartItem.objects.filter(product=product, user=current_user).exists()
        if is_cart_item_exist:
            cart_item = CartItem.objects.filter(product=product, user=current_user)
            ex_var_list = []
            id = []
            for item in cart_item:
                existing_variation = item.variation.all()
                ex_var_list.append(list(existing_variation))
                id.append(item.id)
            if product_variation in ex_var_list:
                index = ex_var_list.index(product_variation)
                item_id = id[index]
                item = CartItem.objects.get(product=product, id=item_id)
                item.quantity += 1
                item.save()
            else:
                item = CartItem.objects.create(product=product, quantity=1, user=current_user)
                if len(product_variation) > 0:
                    item.variation.clear()
                    item.variation.add(*product_variation)
                item.save()
        else:
            cart_item = CartItem.objects.create(
                product=product,
                quantity=1,
                user=current_user,
            )
            if len(product_variation) > 0:
                cart_item.variation.clear()
                cart_item.variation.add(*product_variation)
            cart_item.save()
        return redirect('cart')
    else:
        product_variation = []
        if request.method == 'POST':
            for item in request.POST:
                key = item
                value = request.POST[key]
                try:
                    variation = Variation.objects.get(product=product, variation_category__iexact=key, variation_value__iexact=value)
                    product_variation.append(variation)
                except:
                    pass
        try:
            cart = Cart.objects.get(cart_id=_cart_id(request))
        except Cart.DoesNotExist:
            cart = Cart.objects.create(cart_id=_cart_id(request))
        cart.save()
        is_cart_item_exist = CartItem.objects.filter(product=product, cart=cart).exists()
        if is_cart_item_exist:
            cart_item = CartItem.objects.filter(product=product, cart=cart)
            ex_var_list = []
            id = []
            for item in cart_item:
                existing_variation = item.variation.all()
                ex_var_list.append(list(existing_variation))
                id.append(item.id)
            if product_variation in ex_var_list:
                index = ex_var_list.index(product_variation)
                item_id = id[index]
                item = CartItem.objects.get(product=product, id=item_id)
                item.quantity += 1
                item.save()
            else:
                item = CartItem.objects.create(product=product, quantity=1, cart=cart)
                if len(product_variation) > 0:
                    item.variation.clear()
                    item.variation.add(*product_variation)
                item.save()
        else:
            cart_item = CartItem.objects.create(
                product=product,
                quantity=1,
                cart=cart,
            )
            if len(product_variation) > 0:
                cart_item.variation.clear()
                cart_item.variation.add(*product_variation)
            cart_item.save()
        return redirect('cart')


def _current_cart_items(request):
    if request.user.is_authenticated:
        return CartItem.objects.filter(user=request.user, is_active=True)
    try:
        cart = Cart.objects.get(cart_id=_cart_id(request))
    except ObjectDoesNotExist:
        return CartItem.objects.none()
    return CartItem.objects.filter(cart=cart, is_active=True)


def _priced_context(request, cart_items):
    coupon, problem = session_coupon(request, cart_items)
    if problem:
        messages.info(request, problem)
    pricing = price_cart(cart_items, coupon)
    return {**pricing_context(pricing), 'cart_items': cart_items, 'line_discounts': pricing.line_discounts}


def cart(request):
    cart_items = _current_cart_items(request)
    return render(request, 'store/cart.html', _priced_context(request, cart_items))

def remove_cart(request, product_id, cart_item_id):
    product = get_object_or_404(Product, id=product_id)
    try:
        if request.user.is_authenticated:
            cart_item = CartItem.objects.get(product=product, user=request.user, id = cart_item_id)
        else:
            cart = Cart.objects.get(cart_id = _cart_id(request))
            cart_item = CartItem.objects.get(product=product, cart=cart, id = cart_item_id)
        if cart_item.quantity > 1:
            cart_item.quantity -= 1
            cart_item.save()
        else:
            cart_item.delete()
    except:
        pass

    return redirect('cart')

def remove_cart_item(request, product_id, cart_item_id):
    product = get_object_or_404(Product, id=product_id)
    if request.user.is_authenticated:
        cart_item = CartItem.objects.get(product=product, user=request.user, id = cart_item_id)
    else:
        cart = Cart.objects.get(cart_id = _cart_id(request))
        cart_item = CartItem.objects.get(product=product, cart=cart, id = cart_item_id)
    cart_item.delete()
    return redirect('cart')

@login_required(login_url='login')
def checkout(request):
    cart_items = _current_cart_items(request)
    context = _priced_context(request, cart_items)
    context['checkout_page'] = True
    return render(request, 'store/checkout.html', context)


def _back(request, fallback='cart'):
    target = request.POST.get('next')
    if target and url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}):
        return redirect(target)
    return redirect(fallback)


@require_POST
@login_required(login_url='login')
def apply_coupon(request):
    """Coupons belong to one account: the lookup is always scoped to request.user."""
    code = (request.POST.get('coupon_code') or '').strip()
    coupon = find_coupon(code, request.user)
    problem = check_coupon(coupon, list(_current_cart_items(request))) if code else "Please enter a coupon code."
    if problem:
        request.session.pop(SESSION_KEY, None)
        messages.error(request, problem)
    else:
        request.session[SESSION_KEY] = coupon.code
        messages.success(request, f"Coupon {coupon.code} applied: {coupon.percent}% off up to "
                                  f"{coupon.max_units} × {coupon.product.product_name}.")
    return _back(request)


@require_POST
@login_required(login_url='login')
def remove_coupon(request):
    request.session.pop(SESSION_KEY, None)
    messages.info(request, "Coupon removed.")
    return _back(request)
