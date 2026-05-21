from django import forms
from .models import Order


class OrderForm(forms.ModelForm):
    
    def clean_phone(self):
        phone = self.cleaned_data['phone']
        if len(phone) != 10:
            raise forms.ValidationError("Phone number must be exactly 10 digits")
        return phone
    
    class Meta:
        model = Order
        fields = ['first_name', 'last_name', 'phone', 'email', 'address_line_1', 'address_line_2', 'pin_code', 'city', 'state', 'country', 'order_note']