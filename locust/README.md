# Locust Load Tests — E-Commerce Backend

This directory contains the [Locust](https://locust.io/) load testing configuration for the E-Commerce FastAPI backend.

## Quick Start

### 1. Install Locust
```bash
pip install locust
```

Or use the provided file:
```bash
pip install -r locust/requirements_locust.txt
```

### 2. Start the Backend
Make sure your backend is running first (via Docker Compose):
```bash
docker compose up
```
The API will be available at `http://localhost:8000`.

### 3. Run Locust

**Web UI mode** (recommended for exploration):
```bash
locust -f locust/locustfile.py --host=http://localhost:8000
# Then open http://localhost:8089
```

**Headless / CI mode** (no browser needed):
```bash
locust -f locust/locustfile.py \
  --host=http://localhost:8000 \
  --users 100 \
  --spawn-rate 10 \
  --run-time 2m \
  --headless \
  --csv=locust/results/report
```

---

## User Classes & Traffic Weights

| User Class     | Weight | Description |
|----------------|--------|-------------|
| `PublicUser`   | 60 %   | Anonymous visitor — browses products & categories, no login |
| `CustomerUser` | 30 %   | Logged-in shopper — full cart → checkout → review journey |
| `SellerUser`   |  8 %   | Seller — creates products, views & manages orders/returns |
| `AdminUser`    |  2 %   | Admin — reads platform dashboards (customers, orders, tickets) |

---

## Routes Covered

### Auth (`/auth`)
| Route | Covered By |
|---|---|
| `POST /auth/register` | CustomerUser, SellerUser |
| `POST /auth/login` | CustomerUser, SellerUser, AdminUser |
| `POST /auth/logout` | All authenticated users (`on_stop`) |
| `POST /auth/refresh` | CustomerUser |
| `GET  /auth/role_id` | CustomerUser |

### Products (`/products`)
| Route | Covered By |
|---|---|
| `GET  /products/` | PublicUser, CustomerUser |
| `GET  /products/?search=[term]` | PublicUser |
| `GET  /products/?category_id=[id]` | PublicUser |
| `GET  /products/[id]` | PublicUser, CustomerUser |
| `POST /products/` | SellerUser |
| `PUT  /products/[id]` | SellerUser |
| `PATCH /products/[id]` | SellerUser |

### Categories (`/categories`)
| Route | Covered By |
|---|---|
| `GET /categories/` | PublicUser, SellerUser |

### Cart (`/cart`)
| Route | Covered By |
|---|---|
| `GET  /cart/` | CustomerUser |
| `POST /cart/` | CustomerUser |
| `PUT  /cart/[id]` | CustomerUser |

### Orders (`/orders`)
| Route | Covered By |
|---|---|
| `POST /orders/checkout` | CustomerUser |
| `GET  /orders/` | CustomerUser, SellerUser |

### Reviews (`/reviews`)
| Route | Covered By |
|---|---|
| `POST /reviews/` | CustomerUser |
| `GET  /reviews/product/[id]` | PublicUser |
| `GET  /reviews/seller/[id]` | SellerUser |

### Returns (`/returns`)
| Route | Covered By |
|---|---|
| `POST /returns/` | CustomerUser |
| `GET  /returns/` | CustomerUser, SellerUser, AdminUser |

### Support (`/support`)
| Route | Covered By |
|---|---|
| `POST /support/` | CustomerUser |
| `GET  /support/` | CustomerUser |

### Addresses (`/addresses`)
| Route | Covered By |
|---|---|
| `POST /addresses/` | CustomerUser, SellerUser |
| `GET  /addresses/` | CustomerUser |

### Profiles
| Route | Covered By |
|---|---|
| `POST /customer/onboarding` | CustomerUser |
| `GET  /customer/me` | CustomerUser |
| `POST /seller/onboarding` | SellerUser |
| `GET  /seller/me` | SellerUser |

### Admin (`/admin`)
| Route | Covered By |
|---|---|
| `GET /admin/customers` | AdminUser |
| `GET /admin/sellers` | AdminUser |
| `GET /admin/products` | AdminUser |
| `GET /admin/orders` | AdminUser |
| `GET /admin/support` | AdminUser |

### Health
| Route | Covered By |
|---|---|
| `GET /health` | PublicUser |

---

## Admin Credentials

The `AdminUser` class reads credentials from environment variables:

```bash
export ADMIN_EMAIL=admin@example.com
export ADMIN_PASSWORD=AdminPass@123
```

Or edit `AdminJourneyTasks.ADMIN_EMAIL/ADMIN_PASSWORD` directly in `locustfile.py`.

---

## Recommended Load Profiles

### Smoke Test (sanity check, 5 users)
```bash
locust -f locust/locustfile.py --host=http://localhost:8000 \
  --users 5 --spawn-rate 1 --run-time 30s --headless
```

### Load Test (normal traffic, 100 users)
```bash
locust -f locust/locustfile.py --host=http://localhost:8000 \
  --users 100 --spawn-rate 10 --run-time 5m --headless \
  --csv=locust/results/load
```

### Stress Test (find breaking point, 300 users)
```bash
locust -f locust/locustfile.py --host=http://localhost:8000 \
  --users 300 --spawn-rate 20 --run-time 5m --headless \
  --csv=locust/results/stress
```

### Spike Test (sudden traffic burst)
Use the Web UI → manually set users to 10, then jump to 200 in one click.

---

## Output Reports

When using `--csv=locust/results/report`, Locust writes:
- `report_stats.csv` — per-endpoint RPS, latency (p50/p95/p99), failure rate
- `report_stats_history.csv` — time-series data for graphing
- `report_failures.csv` — failed request details

---

## Key Engineering Features Tested

| Feature | How it's tested |
|---|---|
| **Row-level locking (checkout)** | Multiple CustomerUsers hit `/orders/checkout` concurrently |
| **Redis write-through cache** | PublicUsers hammer `/products/` → cache hit rate visible in logs |
| **Cursor pagination** | Cart/order list endpoints support `cursor` & `limit` params |
| **Rate limiting** | Auth endpoints: register (10/hr), login (5/min), forgot-pw (3/hr) |
| **Role-based access** | Separate user classes with correct `role_id` at registration |
| **Background tasks** | Checkout triggers Celery email task; response time should stay low |
