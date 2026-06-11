# E-Commerce Backend API

> A production-ready, scalable, multi-vendor e-commerce REST API built with **FastAPI**, **PostgreSQL**, and **Redis** — engineered with real-world performance and security challenges in mind.

---

## Table of Contents

- [Overview](#overview)
- [Key Engineering Highlights](#key-engineering-highlights)
- [Tech Stack](#tech-stack)
- [Architecture](#architecture)
- [API Endpoints](#api-endpoints)
- [Project Structure](#project-structure)
- [Environment Variables](#environment-variables)
- [Getting Started (Docker)](#getting-started-docker)
- [Running Tests](#running-tests)

---

## Overview

This is a fully asynchronous backend service for a multi-vendor e-commerce platform. It supports three distinct roles — **Customer**, **Seller**, and **Admin** — each with scoped access to the system. The API handles everything from product listings, shopping cart, and checkout to support tickets, return requests, and seller analytics.

---

## Key Engineering Highlights

These are the specific, real-world engineering problems this project solves:

| Problem | Solution |
|---|---|
| **Concurrency / Race Conditions** | PostgreSQL row-level locking (`SELECT ... FOR UPDATE`) during checkout to prevent overselling the last item in stock |
| **N+1 Query Problem** | SQLAlchemy `selectinload` for eager-loading related entities (products → images, orders → items) in a single query |
| **Slow Queries on Large Tables** | Database indexing on frequently-queried columns |
| **API Performance (Caching)** | Redis-backed **write-through cache** with TTL for high-read endpoints like product listings |
| **Scalable Pagination** | **Cursor-based pagination** (instead of OFFSET/LIMIT) for O(1) paging regardless of dataset size |
| **Non-blocking Background Jobs** | **Celery + Redis** task queue for email notifications, keeping API response times low |
| **Connection Pool Exhaustion** | **PgBouncer** for database connection pooling, preventing DB overload under high traffic |
| **API Abuse / DDoS** | **FastAPI-Limiter** with `pyrate-limiter` for per-route rate limiting (e.g., login: 5 req/min, forgot-password: 3 req/hr) |

---

## Tech Stack

**Core**
- 🐍 **Python 3.11+**
- ⚡ **FastAPI** — Async web framework
- 🗄️ **PostgreSQL** — Primary database (via `asyncpg`)
- 🔥 **SQLAlchemy 2.0** — Async ORM
- 📦 **Alembic** — Database migrations
- ✅ **Pydantic v2** — Data validation & settings

**Infrastructure**
- 🐳 **Docker & Docker Compose** — Containerised development & deployment
- 🔴 **Redis** — Caching layer & Celery message broker
- 🌿 **Celery** — Async background task queue
- 🔀 **PgBouncer** — PostgreSQL connection pooling
- ☁️ **Supabase** — Object storage (product images)

**Security**
- 🔐 **JWT (Access + Refresh Tokens)** — Stateless authentication with token rotation
- 🍪 **HttpOnly Cookies** — Secure token storage (prevents XSS)
- 🚫 **Redis Token Blacklist** — Instant token revocation on logout
- 🛡️ **FastAPI-Limiter** — Rate limiting on all sensitive endpoints

**Testing**
- 🧪 **Pytest** + **pytest-asyncio** — Async unit & integration tests

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        Client (Frontend)                    │
└────────────────────────────┬────────────────────────────────┘
                             │ HTTP
                             ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI Application                     │
│  ┌────────────┐  ┌─────────────┐  ┌──────────────────────┐  │
│  │  Auth/JWT  │  │ Rate Limiter│  │   CORS Middleware    │  │
│  └────────────┘  └─────────────┘  └──────────────────────┘  │
│                                                             │
│  Routers: auth · customer · seller · admin · products       │
│           cart · orders · reviews · returns · support       │
└──────┬────────────────┬────────────────────────────────────-┘
       │                │
       ▼                ▼
┌────────────┐   ┌──────────────┐   ┌───────────────────────┐
│ PostgreSQL │   │    Redis     │   │   Celery Worker       │
│ (asyncpg)  │   │ Cache + Queue│   │ (Email Notifications) │
│ PgBouncer  │   │              │   │                       │
└────────────┘   └──────────────┘   └───────────────────────┘
```

**Role-Based Access Control (RBAC)**

| Role ID | Role | Permissions |
|---|---|---|
| `1` | Customer | Browse products, manage cart, place orders, submit reviews & returns |
| `2` | Seller | Manage own products & inventory, view own orders, handle returns |
| `3` | Admin | Full platform access, manage all users, products, support tickets |

---

## API Endpoints

### 🔑 Auth (`/auth`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/auth/register` | Register a new user | Public |
| `POST` | `/auth/login` | Login (returns JWT + sets HttpOnly cookie) | Public |
| `POST` | `/auth/logout` | Logout & blacklist tokens in Redis | 🔒 Required |
| `POST` | `/auth/refresh` | Rotate access & refresh tokens | 🔒 Required |
| `POST` | `/auth/forgot-password` | Send password reset link (rate limited: 3/hr) | Public |
| `POST` | `/auth/reset-password` | Reset password with token | Public |
| `GET`  | `/auth/role_id` | Get current user's role | 🔒 Required |

### 🛍️ Products (`/products`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/products/` | List all products (cached, cursor-paginated) | Public |
| `GET` | `/products/{id}` | Get a single product | Public |
| `POST` | `/products/` | Create a product | 🔒 Seller |
| `PUT` | `/products/{id}` | Update a product | 🔒 Seller |
| `DELETE` | `/products/{id}` | Delete a product | 🔒 Seller |
| `POST` | `/products/{id}/images` | Upload product images (Supabase) | 🔒 Seller |

### 🛒 Cart (`/cart`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/cart/` | View current cart | 🔒 Customer |
| `POST` | `/cart/` | Add item to cart | 🔒 Customer |
| `PUT` | `/cart/{id}` | Update item quantity | 🔒 Customer |
| `DELETE` | `/cart/{id}` | Remove item from cart | 🔒 Customer |

### 📦 Orders (`/orders`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/orders/checkout` | Checkout cart → create orders (row-locked) | 🔒 Customer |
| `GET` | `/orders/` | List orders (scoped by role, cursor-paginated) | 🔒 Required |
| `PUT` | `/orders/{id}/status` | Update order status | 🔒 Seller |

### ⭐ Reviews (`/reviews`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/reviews/` | Submit a product review | 🔒 Customer |
| `GET` | `/reviews/{product_id}` | Get reviews for a product | Public |
| `DELETE` | `/reviews/{id}` | Delete a review | 🔒 Customer/Admin |

### 🔄 Returns (`/returns`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/returns/` | Request a return | 🔒 Customer |
| `GET` | `/returns/` | List return requests (scoped by role) | 🔒 Required |
| `PUT` | `/returns/{id}/status` | Approve/reject a return | 🔒 Seller/Admin |

### 🎧 Support (`/support`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/support/` | Create a support ticket | 🔒 Required |
| `GET` | `/support/` | List tickets | 🔒 Required |
| `POST` | `/support/{id}/reply` | Reply to a ticket | 🔒 Required |

### 🏠 Addresses (`/addresses`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `POST` | `/addresses/` | Add a new address | 🔒 Customer |
| `GET` | `/addresses/` | List saved addresses | 🔒 Customer |
| `DELETE` | `/addresses/{id}` | Delete an address | 🔒 Customer |

### 📂 Categories (`/categories`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/categories/` | List all categories | Public |
| `POST` | `/categories/` | Create a category | 🔒 Admin |

### 👤 Profiles
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/customer/me` | Get customer profile | 🔒 Customer |
| `PUT` | `/customer/me` | Update customer profile | 🔒 Customer |
| `GET` | `/seller/me` | Get seller profile | 🔒 Seller |
| `PUT` | `/seller/me` | Update seller profile | 🔒 Seller |

### ⚙️ Admin (`/admin`)
| Method | Endpoint | Description | Auth |
|---|---|---|---|
| `GET` | `/admin/customers` | List all customers | 🔒 Admin |
| `GET` | `/admin/sellers` | List all sellers | 🔒 Admin |
| `GET` | `/admin/products` | List all products | 🔒 Admin |
| `GET` | `/admin/orders` | List all orders | 🔒 Admin |
| `GET` | `/admin/support` | View all support tickets | 🔒 Admin |
| `POST` | `/admin/support/{id}/reply` | Reply to any support ticket | 🔒 Admin |

---

## Project Structure

```
.
├── app/
│   ├── main.py                  # FastAPI app entry point, router registration
│   ├── api/
│   │   ├── deps.py              # Dependency injection (get_db, get_current_user, get_redis)
│   │   └── endpoints/           # Route handlers (one file per domain)
│   │       ├── auth.py
│   │       ├── product.py
│   │       ├── cart.py
│   │       ├── order.py
│   │       ├── review.py
│   │       ├── return.py
│   │       ├── support.py
│   │       ├── admin.py
│   │       ├── customer.py
│   │       ├── seller.py
│   │       ├── address.py
│   │       └── category.py
│   ├── core/
│   │   ├── config.py            # Pydantic settings (loaded from .env)
│   │   ├── database.py          # Async SQLAlchemy engine & session
│   │   ├── cache.py             # Redis cache helpers (get, set, invalidate)
│   │   ├── celery_app.py        # Celery instance configuration
│   │   ├── init_db.py           # Seed initial roles/data
│   │   └── security.py          # JWT creation & verification, password hashing
│   ├── models/                  # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── customer.py
│   │   ├── seller.py
│   │   ├── product.py
│   │   ├── category.py
│   │   ├── cart.py
│   │   ├── order.py
│   │   ├── review.py
│   │   ├── address.py
│   │   ├── notification.py
│   │   ├── return_request.py
│   │   ├── stock_history.py
│   │   ├── support.py
│   │   └── role.py
│   ├── schemas/                 # Pydantic v2 request/response schemas
│   └── tasks/
│       └── email.py             # Celery tasks (order confirmation emails via SMTP)
├── alembic/                     # Database migration scripts
├── tests/                       # Pytest test suite
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── .env                         # (not committed) Environment configuration
```

---

## Environment Variables

Create a `.env` file in the project root. See below for all required variables:

```env
# App
APP_NAME=E-Commerce API
DEBUG=True
VERSION=1.0.0

# Database
DATABASE_URL=postgresql+asyncpg://postgres:postgres@db:5432/ecommerce

# Redis & Celery
REDIS_URL=redis://redis:6379/0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0

# JWT Authentication
SECRET_KEY=your-super-secret-key-here
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=30
REFRESH_TOKEN_EXPIRE_DAYS=7

# Supabase (Object Storage for product images)
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_KEY=your-supabase-anon-key

# Business Logic
PLATFORM_COMMISSION_PERCENT=5.0
LOW_STOCK_THRESHOLD=10

# Email (SMTP)
SMTP_SERVER=smtp.gmail.com
SMTP_PORT=587
SENDER_EMAIL=your-email@gmail.com
SENDER_PASSWORD=your-app-password
```

---

## Getting Started (Docker)

> **Prerequisites:** [Docker](https://www.docker.com/) and [Docker Compose](https://docs.docker.com/compose/)

**1. Clone the repository**
```bash
git clone https://github.com/nithin01010/E-commerce-Backed.git
cd E-commerce-Backed
```

**2. Create your `.env` file**
```bash
cp .env.example .env
# Edit .env with your values
```

**3. Build and start all services**
```bash
docker compose up --build
```

This will start:
- 🌐 **FastAPI** app on `http://localhost:8000`
- 🗄️ **PostgreSQL** on `localhost:5433`
- 🔴 **Redis** on `localhost:6380`
- 🌿 **Celery Worker** for background tasks

Database migrations (`alembic upgrade head`) and initial data seeding run **automatically** on startup.

**4. Explore the API**

Visit the interactive API docs at:
- **Swagger UI:** `http://localhost:8000/docs`
- **ReDoc:** `http://localhost:8000/redoc`

---

## Running Tests

```bash
# Run all tests inside the container
docker compose exec web pytest

# Or run locally with venv activated
pytest -v
```

---

## Health Check

```bash
GET /health
→ { "status": "ok" }
```
