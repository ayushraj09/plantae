from django.test import TestCase
from django.urls import reverse

from accounts.models import Account, UserProfile


class DashboardTests(TestCase):
    def test_dashboard_works_for_account_without_profile(self):
        # e.g. created with createsuperuser / admin, which skip registration
        user = Account.objects.create_user("No", "Profile", "noprofile", "noprofile@example.com", "pw",
                                           phone_number="9000000009")
        user.is_active = True
        user.save()
        self.assertFalse(UserProfile.objects.filter(user=user).exists())
        self.client.force_login(user)
        self.assertEqual(self.client.get(reverse("dashboard")).status_code, 200)
        self.assertEqual(UserProfile.objects.filter(user=user).count(), 1)
        self.assertEqual(self.client.get(reverse("edit_profile")).status_code, 200)
