"""
E-Commerce Backend — Locust Load Test Suite
============================================
Target:    http://localhost:8000
Run with:  locust -f locust/locustfile.py --host=http://localhost:8000

Roles simulated
---------------
- PublicUser   : Browse products & categories (no auth required)
- CustomerUser : Register → onboard → add to cart → checkout → review
- SellerUser   : Register → onboard → create product → manage orders
- AdminUser    : View admin dashboards (customers, sellers, products, orders)

Weights (realistic traffic split)
----------------------------------
- PublicUser   60 %  — highest; most visitors never log in
- CustomerUser 30 %  — logged-in shoppers
- SellerUser    8 %  — sellers managing inventory
- AdminUser     2 %  — admins monitoring platform

Quick-start
-----------
  pip install locust
  locust -f locust/locustfile.py --host=http://localhost:8000 --users 100 --spawn-rate 10
  # Open http://localhost:8089 in your browser

Headless (CI) example
---------------------
  locust -f locust/locustfile.py \\
    --host=http://localhost:8000 \\
    --users 50 --spawn-rate 5 \\
    --run-time 2m --headless \\
    --csv=locust/results/report

Admin credentials
-----------------
  Set ADMIN_EMAIL / ADMIN_PASSWORD env vars OR edit AdminJourneyTasks directly.
"""

import os
import random
import string

from locust import HttpUser, TaskSet, task, between


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _random_email() -> str:
    suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
    return f"loadtest_{suffix}@example.com"


def _random_str(n: int = 8) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=n))


def _random_phone() -> str:
    return "9" + "".join(random.choices(string.digits, k=9))


# ---------------------------------------------------------------------------
# Shared state: product/category ID pools populated at runtime
# ---------------------------------------------------------------------------

_product_id_pool: list[int] = []
_category_id_pool: list[int] = [1, 2, 3]   # seeded; extended during test


# ---------------------------------------------------------------------------
# Public Task Set  (no auth required)
# ---------------------------------------------------------------------------

class PublicBrowsingTasks(TaskSet):
    """Anonymous visitor — product & category browsing."""

    @task(5)
    def health_check(self):
        self.client.get("/health", name="/health")

    @task(20)
    def list_products(self):
        resp = self.client.get("/products/", name="/products/ [list]")
        if resp.status_code == 200:
            for p in resp.json():
                pid = p.get("id")
                if pid and pid not in _product_id_pool:
                    _product_id_pool.append(pid)

    @task(10)
    def search_products(self):
        terms = ["shirt", "phone", "book", "laptop", "shoes", "watch"]
        q = random.choice(terms)
        self.client.get(f"/products/?search={q}", name="/products/?search=[term]")

    @task(8)
    def filter_by_category(self):
        if _category_id_pool:
            cat_id = random.choice(_category_id_pool)
            self.client.get(
                f"/products/?category_id={cat_id}",
                name="/products/?category_id=[id]",
            )

    @task(12)
    def get_product_detail(self):
        pid = random.choice(_product_id_pool) if _product_id_pool else 1
        self.client.get(f"/products/{pid}", name="/products/[id]")

    @task(8)
    def list_categories(self):
        resp = self.client.get("/categories/", name="/categories/")
        if resp.status_code == 200:
            for cat in resp.json():
                cid = cat.get("id")
                if cid and cid not in _category_id_pool:
                    _category_id_pool.append(cid)

    @task(6)
    def get_product_reviews(self):
        if _product_id_pool:
            pid = random.choice(_product_id_pool)
            self.client.get(f"/reviews/product/{pid}", name="/reviews/product/[id]")


# ---------------------------------------------------------------------------
# Customer Task Set
# ---------------------------------------------------------------------------

class CustomerJourneyTasks(TaskSet):
    """
    Full customer lifecycle:
      register → onboard → add address → browse → cart → checkout → review
    """

    def on_start(self):
        self.token: str | None = None
        self.refresh_token: str | None = None
        self.address_id: int | None = None
        self.cart_item_id: int | None = None
        self.order_id: int | None = None
        self.email = _random_email()
        self.password = "TestPass@123"
        self._register_and_login()
        self._onboard()
        self._add_address()

    # ---- helpers --------------------------------------------------------

    def _hdrs(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _register_and_login(self):
        self.client.post(
            "/auth/register",
            json={"email": self.email, "password": self.password, "role_id": 1},
            name="/auth/register [customer]",
        )
        resp = self.client.post(
            "/auth/login",
            data={"username": self.email, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/login [customer]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")
            self.refresh_token = resp.json().get("refresh_token")

    def _onboard(self):
        if not self.token:
            return
        self.client.post(
            "/customer/onboarding",
            json={
                "name": f"Customer {_random_str(5)}",
                "phone_number": _random_phone(),
            },
            headers=self._hdrs(),
            name="/customer/onboarding",
        )

    def _add_address(self):
        if not self.token:
            return
        resp = self.client.post(
            "/addresses/",
            json={
                "full_name": "Load Tester",
                "phone": _random_phone(),
                "street": f"{random.randint(1, 999)} Test Street",
                "city": "TestCity",
                "state": "TestState",
                "pincode": "600001",
                "country": "India",
                "is_default": True,
            },
            headers=self._hdrs(),
            name="/addresses/ [create]",
        )
        if resp.status_code == 201:
            self.address_id = resp.json().get("id")

    # ---- recurring tasks ------------------------------------------------

    # @task(15)
    # def browse_products(self):
    #     resp = self.client.get("/products/", name="/products/ [customer]")
    #     if resp.status_code == 200:
    #         for p in resp.json():
    #             pid = p.get("id")
    #             if pid and pid not in _product_id_pool:
    #                 _product_id_pool.append(pid)

    # @task(10)
    # def view_product_detail(self):
    #     if _product_id_pool:
    #         pid = random.choice(_product_id_pool)
    #         self.client.get(f"/products/{pid}", name="/products/[id] [customer]")

    # @task(8)
    # def view_my_profile(self):
    #     if not self.token:
    #         return
    #     self.client.get("/customer/me", headers=self._hdrs(), name="/customer/me")

    # @task(5)
    # def view_my_addresses(self):
    #     if not self.token:
    #         return
    #     self.client.get("/addresses/", headers=self._hdrs(), name="/addresses/ [list]")

    @task(15)
    def add_to_cart(self):
        if not self.token or not _product_id_pool:
            return
        pid = random.choice(_product_id_pool)
        resp = self.client.post(
            "/cart/",
            json={"product_id": pid, "quantity": random.randint(1, 2)},
            headers=self._hdrs(),
            name="/cart/ [add]",
        )
        if resp.status_code == 201:
            self.cart_item_id = resp.json().get("id")

    # @task(5)
    # def view_cart(self):
    #     if not self.token:
    #         return
    #     self.client.get("/cart/", headers=self._hdrs(), name="/cart/ [list]")

    @task(12)
    def update_cart_quantity(self):
        if not self.token or not self.cart_item_id:
            return
        self.client.put(
            f"/cart/{self.cart_item_id}",
            json={"quantity": random.randint(1, 3)},
            headers=self._hdrs(),
            name="/cart/[id] [update]",
        )

    @task(10)
    def remove_from_cart(self):
        if not self.token or not self.cart_item_id:
            return
        resp = self.client.delete(
            f"/cart/{self.cart_item_id}",
            headers=self._hdrs(),
            name="/cart/[id] [delete]",
        )
        if resp.status_code == 204:
            self.cart_item_id = None

    @task(10)
    def checkout(self):
        if not self.token or not self.address_id or not self.cart_item_id:
            return
        resp = self.client.post(
            "/orders/checkout",
            json={"address_id": self.address_id},
            headers=self._hdrs(),
            name="/orders/checkout",
        )
        if resp.status_code == 201:
            self.cart_item_id = None
            orders = resp.json()
            if orders:
                self.order_id = orders[0].get("id")

    # @task(5)
    # def list_orders(self):
    #     if not self.token:
    #         return
    #     self.client.get("/orders/", headers=self._hdrs(), name="/orders/ [customer]")

    @task(8)
    def submit_review(self):
        if not self.token or not self.order_id:
            return
        resp = self.client.post(
            "/reviews/",
            json={
                "order_id": self.order_id,
                "rating": random.randint(3, 5),
                "comment": f"Great product! {_random_str(10)}",
            },
            headers=self._hdrs(),
            name="/reviews/ [create]",
        )
        if resp.status_code == 201:
            self.order_id = None

    @task(8)
    def request_return(self):
        if not self.token or not self.order_id:
            return
        resp = self.client.post(
            "/returns/",
            json={"order_id": self.order_id, "comment": "Item damaged on delivery."},
            headers=self._hdrs(),
            name="/returns/ [create]",
        )
        if resp.status_code == 201:
            self.order_id = None

    @task(3)
    def list_my_returns(self):
        if not self.token:
            return
        self.client.get("/returns/", headers=self._hdrs(), name="/returns/ [customer]")

    @task(8)
    def create_support_ticket(self):
        if not self.token:
            return
        self.client.post(
            "/support/",
            json={
                "subject": f"Issue {_random_str(4)}",
                "description": "My order has not arrived yet.",
                "priority": random.choice(["low", "medium", "high"]),
            },
            headers=self._hdrs(),
            name="/support/ [create]",
        )

    @task(3)
    def list_support_tickets(self):
        if not self.token:
            return
        self.client.get("/support/", headers=self._hdrs(), name="/support/ [list]")

    @task(5)
    def delete_address(self):
        if not self.token or not self.address_id:
            return
        resp = self.client.delete(
            f"/addresses/{self.address_id}",
            headers=self._hdrs(),
            name="/addresses/[id] [delete]",
        )
        if resp.status_code == 204:
            self.address_id = None

    @task(1)
    def refresh_token(self):
        if not self.refresh_token:
            return
        resp = self.client.post(
            "/auth/refresh",
            headers={**self._hdrs(), "X-Refresh-Token": self.refresh_token},
            name="/auth/refresh",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")
            self.refresh_token = resp.json().get("refresh_token")

    @task(1)
    def get_role_id(self):
        if not self.token:
            return
        self.client.get("/auth/role_id", headers=self._hdrs(), name="/auth/role_id")

    def on_stop(self):
        if self.token:
            self.client.post(
                "/auth/logout", headers=self._hdrs(), name="/auth/logout [customer]"
            )


# ---------------------------------------------------------------------------
# Seller Task Set
# ---------------------------------------------------------------------------

class SellerJourneyTasks(TaskSet):
    """
    Seller lifecycle:
      register → onboard → create products → view/update orders → returns
    """

    def on_start(self):
        self.token: str | None = None
        self.product_id: int | None = None
        self.email = _random_email()
        self.password = "SellerPass@123"
        self._register_and_login()
        self._onboard()
        self._create_product()

    def _hdrs(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _register_and_login(self):
        self.client.post(
            "/auth/register",
            json={"email": self.email, "password": self.password, "role_id": 2},
            name="/auth/register [seller]",
        )
        resp = self.client.post(
            "/auth/login",
            data={"username": self.email, "password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/login [seller]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

    def _onboard(self):
        if not self.token:
            return
        self.client.post(
            "/seller/onboarding",
            json={"name": f"Seller {_random_str(5)}", "phone_number": _random_phone()},
            headers=self._hdrs(),
            name="/seller/onboarding",
        )

    def _create_product(self):
        if not self.token:
            return
        cat_id = random.choice(_category_id_pool) if _category_id_pool else 1
        resp = self.client.post(
            "/products/",
            json={
                "name": f"Product {_random_str(6)}",
                "description": f"Load-test product {_random_str(12)}",
                "price": random.randint(10, 1000),
                "stock": random.randint(10, 100),
                "category_id": cat_id,
            },
            headers=self._hdrs(),
            name="/products/ [create]",
        )
        if resp.status_code == 201:
            self.product_id = resp.json().get("id")
            if self.product_id and self.product_id not in _product_id_pool:
                _product_id_pool.append(self.product_id)

    # ---- recurring tasks ------------------------------------------------

    @task(10)
    def view_my_seller_profile(self):
        if not self.token:
            return
        self.client.get("/seller/me", headers=self._hdrs(), name="/seller/me")

    @task(8)
    def list_my_orders(self):
        if not self.token:
            return
        self.client.get("/orders/", headers=self._hdrs(), name="/orders/ [seller]")

    @task(4)
    def list_my_returns(self):
        if not self.token:
            return
        self.client.get("/returns/", headers=self._hdrs(), name="/returns/ [seller]")

    @task(10)
    def update_product_full(self):
        if not self.token or not self.product_id:
            return
        cat_id = random.choice(_category_id_pool) if _category_id_pool else 1
        self.client.put(
            f"/products/{self.product_id}",
            json={
                "name": f"Updated {_random_str(6)}",
                "description": "Updated via load test",
                "price": random.randint(10, 1000),
                "stock": random.randint(5, 50),
                "category_id": cat_id,
            },
            headers=self._hdrs(),
            name="/products/[id] [PUT]",
        )

    @task(8)
    def patch_product_price(self):
        if not self.token or not self.product_id:
            return
        self.client.patch(
            f"/products/{self.product_id}",
            json={"price": random.randint(50, 500)},
            headers=self._hdrs(),
            name="/products/[id] [PATCH]",
        )

    @task(10)
    def create_another_product(self):
        self._create_product()

    @task(3)
    def view_seller_reviews(self):
        if not self.token:
            return
        self.client.get(
            "/reviews/seller/1",
            headers=self._hdrs(),
            name="/reviews/seller/[id]",
        )

    @task(8)
    def add_seller_address(self):
        if not self.token:
            return
        self.client.post(
            "/addresses/",
            json={
                "full_name": f"Seller {_random_str(5)}",
                "phone": _random_phone(),
                "street": f"{random.randint(1, 999)} Warehouse Rd",
                "city": "ShipCity",
                "state": "ShipState",
                "pincode": "500001",
                "country": "India",
                "is_default": False,
            },
            headers=self._hdrs(),
            name="/addresses/ [seller create]",
        )

    @task(6)
    def delete_my_product(self):
        if not self.token or not self.product_id:
            return
        resp = self.client.delete(
            f"/products/{self.product_id}",
            headers=self._hdrs(),
            name="/products/[id] [delete]",
        )
        if resp.status_code == 204:
            if self.product_id in _product_id_pool:
                _product_id_pool.remove(self.product_id)
            self.product_id = None

    @task(2)
    def view_my_categories(self):
        self.client.get("/categories/", name="/categories/ [seller]")

    def on_stop(self):
        if self.token:
            self.client.post(
                "/auth/logout", headers=self._hdrs(), name="/auth/logout [seller]"
            )


# ---------------------------------------------------------------------------
# Admin Task Set
# ---------------------------------------------------------------------------

class AdminJourneyTasks(TaskSet):
    """
    Admin monitoring:
      list customers, sellers, products, orders, support tickets.
    Set ADMIN_EMAIL / ADMIN_PASSWORD env vars for a real admin account.
    """

    ADMIN_EMAIL = os.getenv("ADMIN_EMAIL", "admin@example.com")
    ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "AdminPass@123")

    def on_start(self):
        self.token: str | None = None
        self._login()

    def _hdrs(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def _login(self):
        resp = self.client.post(
            "/auth/login",
            data={"username": self.ADMIN_EMAIL, "password": self.ADMIN_PASSWORD},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            name="/auth/login [admin]",
        )
        if resp.status_code == 200:
            self.token = resp.json().get("access_token")

    @task(5)
    def list_all_customers(self):
        if not self.token:
            return
        self.client.get("/admin/customers", headers=self._hdrs(), name="/admin/customers")

    @task(5)
    def list_all_sellers(self):
        if not self.token:
            return
        self.client.get("/admin/sellers", headers=self._hdrs(), name="/admin/sellers")

    @task(6)
    def list_all_products(self):
        if not self.token:
            return
        self.client.get("/admin/products", headers=self._hdrs(), name="/admin/products")

    @task(6)
    def list_all_orders(self):
        if not self.token:
            return
        self.client.get("/admin/orders", headers=self._hdrs(), name="/admin/orders")

    @task(4)
    def list_all_support_tickets(self):
        if not self.token:
            return
        self.client.get("/admin/support", headers=self._hdrs(), name="/admin/support")

    @task(3)
    def list_all_returns(self):
        if not self.token:
            return
        self.client.get("/returns/", headers=self._hdrs(), name="/returns/ [admin]")

    def on_stop(self):
        if self.token:
            self.client.post(
                "/auth/logout", headers=self._hdrs(), name="/auth/logout [admin]"
            )


# ---------------------------------------------------------------------------
# Locust User Classes  (entry points — weight controls spawn ratio)
# ---------------------------------------------------------------------------

class PublicUser(HttpUser):
    # """Anonymous visitor. Highest weight — mostly read-only browse traffic."""
    tasks = [PublicBrowsingTasks]
    wait_time = between(1, 3)
    weight = 60


class CustomerUser(HttpUser):
    """Logged-in shopper. Full cart/checkout/review journey."""
    tasks = [CustomerJourneyTasks]
    wait_time = between(2, 5)
    weight = 30


class SellerUser(HttpUser):
    """Seller managing products and orders."""
    tasks = [SellerJourneyTasks]
    wait_time = between(3, 7)
    weight = 8


class AdminUser(HttpUser):
    """Admin reading platform dashboards."""
    tasks = [AdminJourneyTasks]
    wait_time = between(5, 10)
    weight = 2
