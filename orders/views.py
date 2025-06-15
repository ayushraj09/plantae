from django.shortcuts import render, redirect
from carts.models import CartItem
from .forms import OrderForm
import datetime
from .models import Order, OrderProduct, Payment
from django.contrib import messages
import razorpay
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.http import JsonResponse
from store.models import Product

from django.template.loader import render_to_string
from django.core.mail import EmailMessage

# Create your views here.

def payments(request):
    current_user = request.user
    order_obj = Order.objects.filter(user=current_user, is_ordered=False).order_by('-id').first()

    if not order_obj:
        return redirect('store')

    cart_items = CartItem.objects.filter(user=current_user)
    if not cart_items.exists():
        return redirect('store')

    total = 0
    quantity = 0
    for item in cart_items:
        total += item.product.price * item.quantity
        quantity += item.quantity

    tax = (18 * total) / 100
    grand_total = total + tax

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
    DATA = {
        "amount": int(grand_total * 100),
        "currency": "INR",
        "payment_capture": 1,
    }
    payment = client.order.create(data=DATA)
    order_obj.razorpay_order_id = payment['id']
    order_obj.save()

    context = {
        'razorpay_key': settings.RAZORPAY_KEY_ID,
        'order_id': payment['id'],
        'amount': int(grand_total * 100),
        'name': 'PLANTAE',
        'order': order_obj,
        'cart_items': cart_items,
        'total': total,
        'tax': tax,
        'grand_total': grand_total,
    }

    return render(request, 'orders/payments.html', context)


def place_order(request, total=0, quantity=0):
    current_user = request.user
    cart_items = CartItem.objects.filter(user=current_user)

    if not cart_items.exists():
        return redirect('store')

    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            try:
                for item in cart_items:
                    total += item.product.price * item.quantity
                    quantity += item.quantity

                tax = (18 * total) / 100
                grand_total = total + tax

                order = Order()
                order.user = current_user
                order.first_name = form.cleaned_data['first_name']
                order.last_name = form.cleaned_data['last_name']
                order.phone = form.cleaned_data['phone']
                order.email = form.cleaned_data['email']
                order.address_line_1 = form.cleaned_data['address_line_1']
                order.address_line_2 = form.cleaned_data['address_line_2']
                order.pin_code = form.cleaned_data['pin_code']
                order.city = form.cleaned_data['city']
                order.state = form.cleaned_data['state']
                order.country = form.cleaned_data['country']
                order.order_note = form.cleaned_data['order_note']
                order.order_total = grand_total
                order.tax = tax
                order.ip = request.META.get('REMOTE_ADDR')
                order.save()

                current_date = datetime.date.today().strftime("%Y%m%d")
                order_number = current_date + str(order.id)
                order.order_number = order_number
                order.save()

                return redirect('payments')
            except Exception as e:
                messages.error(request, f"Error placing order: {str(e)}")
                return redirect('checkout')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f"{field}: {error}")
            return redirect('checkout')
    else:
        return redirect('checkout')


@csrf_exempt
def razorpay_callback(request):
    if request.method == "POST":
        data = request.POST
        razorpay_payment_id = data.get('razorpay_payment_id')
        razorpay_order_id = data.get('razorpay_order_id')
        razorpay_signature = data.get('razorpay_signature')

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

        params_dict = {
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature
        }

        try:
            # Verify the payment signature
            client.utility.verify_payment_signature(params_dict)

            order = Order.objects.get(razorpay_order_id=razorpay_order_id, is_ordered=False)
            payment = Payment.objects.create(
                user=request.user,
                payment_id=razorpay_payment_id,
                payment_method='Razorpay',
                amount_paid=order.order_total,
                status="Completed"
            )
            order.payment = payment
            order.is_ordered = True
            order.save()

            # Move cart items to OrderProducts
            cart_items = CartItem.objects.filter(user=request.user)
            for item in cart_items:
                orderproduct = OrderProduct()
                orderproduct.order_id = order.id
                orderproduct.payment = payment
                orderproduct.user_id = request.user.id
                orderproduct.product_id = item.product_id
                orderproduct.quantity = item.quantity
                orderproduct.product_price = item.product.price
                orderproduct.ordered = True
                orderproduct.save()

                cart_item = CartItem.objects.get(id = item.id)
                product_variation = cart_item.variation.all()
                orderproduct = OrderProduct.objects.get(id=orderproduct.id)
                orderproduct.variation.set(product_variation)
                orderproduct.save()
                
                #Reduce quantity of sold products
                product = Product.objects.get(id = item.product_id)
                product.stock -= item.quantity
                product.save()

            # delete cart items
            cart_items.delete()

            #send order received email to user
            mail_subject = 'Order Confirmation - PLANTAE'
            message = render_to_string('orders/order_received_email.html', {
                'user': request.user,
                'order': order,
            })
            to_email = request.user.email
            send_email = EmailMessage(mail_subject, message, to=[to_email])
            send_email.send()

            #send order number and tx id
            return redirect('order_success', order_number=order.order_number, payment_id=payment.payment_id)
        except Exception as e:
            return JsonResponse({'error': str(e)}, status=400)

def order_success(request, order_number, payment_id):

    try:
        order = Order.objects.get(order_number=order_number, is_ordered = True)
        ordered_products = OrderProduct.objects.filter(order_id = order.id)
        payment = Payment.objects.get(payment_id=payment_id)
        context = {
            'order': order,
            'order_number': order_number,
            'payment_id': payment_id,
            'ordered_products': ordered_products,
            'payment': payment,
        }
        return render(request, 'orders/order_success.html', context)

    except(Payment.DoesNotExist, Order.DoesNotExist):
        return redirect('home')

