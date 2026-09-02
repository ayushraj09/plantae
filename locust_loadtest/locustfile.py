import os
import random
import re
import time
from itertools import cycle
from urllib.parse import urlparse

from locust import HttpUser, SequentialTaskSet, TaskSet, between, task
from locust.exception import StopUser


HOST = os.getenv("PLANTAE_HOST", "https://plantaeai.tech")

# Provide one or more test accounts as:
# PLANTAE_TEST_USERS="user1@example.com:password,user2@example.com:password"
# or a single account as PLANTAE_TEST_EMAIL / PLANTAE_TEST_PASSWORD.
TEST_USERS = os.getenv("PLANTAE_TEST_USERS", "")
SINGLE_TEST_USER = (
    os.getenv("PLANTAE_TEST_EMAIL", ""),
    os.getenv("PLANTAE_TEST_PASSWORD", ""),
)

# Production-sensitive switches. Keep these disabled for ordinary browse/load
# tests and enable only when the production database can accept test orders.
ENABLE_ORDER_POSTS = os.getenv("PLANTAE_ENABLE_ORDER_POSTS", "false").lower() == "true"
ENABLE_PAYMENT_PAGE = os.getenv("PLANTAE_ENABLE_PAYMENT_PAGE", "false").lower() == "true"
FETCH_STATIC_ASSETS = os.getenv("PLANTAE_FETCH_STATIC", "false").lower() == "true"
STATIC_ASSET_LIMIT = int(os.getenv("PLANTAE_STATIC_ASSET_LIMIT", "12"))

PRODUCT_SLUGS = ["adenium", "rose", "jade"]
SEARCH_TERMS = ["rose", "jade", "soil", "plant"]

# Product IDs fetched from the production store_product table at the time the
# original test was written. Update this list when catalog seed data changes.
PRODUCT_IDS = [1, 2, 3, 5, 6, 8, 9, 10, 11, 12, 13]

STATIC_URL_RE = re.compile(r"""(?:src|href)=["'](?P<url>/(?:static|media)/[^"']+)["']""")
CSRF_RE = re.compile(
    r"""name=["']csrfmiddlewaretoken["']\s+value=["'](?P<token>[^"']+)["']"""
)


def _build_credentials():
    users = []
    if TEST_USERS:
        for raw_user in TEST_USERS.split(","):
            if ":" not in raw_user:
                continue
            email, password = raw_user.split(":", 1)
            if email.strip() and password.strip():
                users.append((email.strip(), password.strip()))

    email, password = SINGLE_TEST_USER
    if email and password:
        users.append((email, password))

    return users


CREDENTIALS = _build_credentials()
CREDENTIAL_CYCLE = cycle(CREDENTIALS) if CREDENTIALS else None


def csrf_token(response):
    match = CSRF_RE.search(response.text)
    if match:
        return match.group("token")
    return response.cookies.get("csrftoken")


def order_payload(email):
    suffix = int(time.time() * 1000) % 100000
    return {
        "first_name": "Load",
        "last_name": "Tester",
        "email": email,
        "phone": "9876543210",
        "address_line_1": "Plantae Load Test Address",
        "address_line_2": f"Run {suffix}",
        "pin_code": "400001",
        "city": "Mumbai",
        "state": "Maharashtra",
        "country": "India",
        "order_note": "Created by Locust load test. Do not fulfill.",
    }


class PlantaeBaseUser(HttpUser):
    abstract = True
    host = HOST
    wait_time = between(1, 5)

    def fetch_static_assets(self, response, page_name):
        if not FETCH_STATIC_ASSETS:
            return

        asset_urls = []
        for match in STATIC_URL_RE.finditer(response.text):
            asset_url = match.group("url")
            if asset_url not in asset_urls:
                asset_urls.append(asset_url)

        for asset_url in asset_urls[:STATIC_ASSET_LIMIT]:
            parsed = urlparse(asset_url)
            asset_type = "media" if parsed.path.startswith("/media/") else "static"
            self.client.get(
                asset_url,
                name=f"Asset: {asset_type} from {page_name}",
                catch_response=False,
            )

    def login_with_next_credential(self):
        if not CREDENTIAL_CYCLE:
            raise StopUser(
                "Set PLANTAE_TEST_USERS or PLANTAE_TEST_EMAIL/PLANTAE_TEST_PASSWORD "
                "to run authenticated load tests."
            )

        email, password = next(CREDENTIAL_CYCLE)
        login_page = self.client.get("/accounts/login/", name="Auth: login page")
        token = csrf_token(login_page)

        with self.client.post(
            "/accounts/login/",
            data={
                "csrfmiddlewaretoken": token,
                "email": email,
                "password": password,
            },
            headers={"Referer": f"{self.host}/accounts/login/"},
            name="Auth: login POST",
            catch_response=True,
            allow_redirects=False,
        ) as response:
            location = response.headers.get("Location", "")
            if response.status_code not in (301, 302) or "login" in location:
                response.failure(
                    "Login failed. Confirm the test account exists and is active."
                )
                raise StopUser("Login failed")

        with self.client.get(
            "/accounts/dashboard/",
            name="Auth: dashboard check",
            catch_response=True,
            allow_redirects=False,
        ) as response:
            if response.status_code != 200:
                response.failure("Authenticated dashboard was not reachable.")
                raise StopUser("Dashboard check failed")

        return email


class AnonymousBrowseJourney(SequentialTaskSet):
    @task
    def view_homepage(self):
        response = self.client.get("/", name="Browse: home")
        self.user.fetch_static_assets(response, "home")

    @task
    def view_store(self):
        response = self.client.get("/store/", name="Browse: store")
        self.user.fetch_static_assets(response, "store")

    @task
    def view_category(self):
        response = self.client.get(
            "/store/category/plants/", name="Browse: plants category"
        )
        self.user.fetch_static_assets(response, "plants category")

    @task
    def search_products(self):
        term = random.choice(SEARCH_TERMS)
        self.client.get(f"/store/search/?keyword={term}", name="Browse: search")

    @task
    def view_product(self):
        slug = random.choice(PRODUCT_SLUGS)
        response = self.client.get(
            f"/store/category/plants/{slug}", name="Browse: product detail"
        )
        self.user.fetch_static_assets(response, "product detail")


class AuthenticatedCustomerJourney(SequentialTaskSet):
    def on_start(self):
        self.email = self.user.login_with_next_credential()

    @task
    def account_pages(self):
        self.client.get("/accounts/dashboard/", name="Account: dashboard")
        self.client.get("/accounts/my_orders/", name="Account: my orders")

    @task
    def browse_as_customer(self):
        slug = random.choice(PRODUCT_SLUGS)
        self.client.get("/", name="Customer: home")
        self.client.get("/store/", name="Customer: store")
        self.client.get(
            f"/store/category/plants/{slug}", name="Customer: product detail"
        )

    @task
    def add_to_cart_post(self):
        product_id = random.choice(PRODUCT_IDS)
        store_page = self.client.get("/store/", name="Cart: store before add")
        token = csrf_token(store_page)
        self.client.post(
            f"/cart/add_cart/{product_id}/",
            data={"csrfmiddlewaretoken": token},
            headers={"Referer": f"{self.user.host}/store/"},
            name="Cart: add item POST",
            allow_redirects=True,
        )
        self.client.get("/cart/", name="Cart: view")

    @task
    def checkout_get(self):
        self.ensure_cart_item()
        self.client.get("/cart/checkout/", name="Checkout: page")

    @task
    def place_order_post(self):
        if not ENABLE_ORDER_POSTS:
            self.checkout_get()
            return

        self.ensure_cart_item()
        checkout_page = self.client.get("/cart/checkout/", name="Checkout: page")
        token = csrf_token(checkout_page)

        with self.client.post(
            "/orders/place_order/",
            data={
                "csrfmiddlewaretoken": token,
                **order_payload(self.email),
            },
            headers={"Referer": f"{self.user.host}/cart/checkout/"},
            name="Checkout: place order POST",
            catch_response=True,
            allow_redirects=False,
        ) as response:
            location = response.headers.get("Location", "")
            if response.status_code not in (301, 302) or "payments" not in location:
                response.failure("Order placement did not redirect to payments.")

        if ENABLE_PAYMENT_PAGE:
            self.client.get("/orders/payments/", name="Checkout: payment page")

    def ensure_cart_item(self):
        product_id = random.choice(PRODUCT_IDS)
        store_page = self.client.get("/store/", name="Cart: seed from store")
        token = csrf_token(store_page)
        self.client.post(
            f"/cart/add_cart/{product_id}/",
            name="Cart: seed item",
            data={"csrfmiddlewaretoken": token},
            headers={"Referer": f"{self.user.host}/store/"},
            allow_redirects=True,
        )


class CartProfilingJourney(TaskSet):
    def on_start(self):
        self.user.login_with_next_credential()

    @task(5)
    def add_cart_only(self):
        product_id = random.choice(PRODUCT_IDS)
        store_page = self.client.get("/store/", name="Profile: cart store page")
        token = csrf_token(store_page)
        self.client.post(
            f"/cart/add_cart/{product_id}/",
            name="Profile: cart add",
            data={"csrfmiddlewaretoken": token},
            headers={"Referer": f"{self.user.host}/store/"},
            allow_redirects=True,
        )

    @task(2)
    def cart_and_checkout_read(self):
        self.client.get("/cart/", name="Profile: cart read")
        self.client.get("/cart/checkout/", name="Profile: checkout read")


class AnonymousBrowseUser(PlantaeBaseUser):
    weight = 4
    tasks = [AnonymousBrowseJourney]


class AuthenticatedCustomerUser(PlantaeBaseUser):
    weight = 3
    tasks = [AuthenticatedCustomerJourney]


class CartProfilingUser(PlantaeBaseUser):
    weight = 1
    wait_time = between(0.5, 2)
    tasks = [CartProfilingJourney]
