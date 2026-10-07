# Plantae 🌱

<p align="center">
  <img src="plantae/static/images/logo.png" alt="Plantae Logo" width="180"/>
</p>

[![MIT License](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

---

## Live Demo

🌐 **Production:** [https://plantaeai.tech](https://plantaeai.tech)

---

## Table of Contents
- [Overview](#overview)
- [Screenshots](#screenshots)
- [Features](#features)
- [AI Agent & Workflow](#ai-agent--workflow)
- [Human-in-the-Loop (Slack)](#human-in-the-loop-slack)
- [Price-Match Coupons](#price-match-coupons)
- [App Structure](#app-structure)
- [Tech Stack](#tech-stack)
- [Getting Started](#getting-started)
- [Load Test Analysis](#load-test-analysis)
- [Deployment](#deployment)
- [License](#license)
- [Contact](#contact)

---

## Overview

**Plantae** is a modern, AI-powered e-commerce platform for plant and gardening products. It features a conversational agent for plant care, product recommendations, and order support. The project is built with Django and deployed on an Azure VM at [plantaeai.tech](https://plantaeai.tech).

---

## Screenshots

| Home Page | Admin |
|-----------|-------|
| ![Home Page](docs/screenshots/home.png) | ![Admin](docs/screenshots/admin.png)|

| Store | Product Detail |
|-------|---------------|
| ![Store](docs/screenshots/store.png) | ![Product Detail](docs/screenshots/product_detail.png) |

| Cart | Payment Success |
|------|----------------|
| ![Cart](docs/screenshots/cart.png) | ![Payment Success](docs/screenshots/payment_success.png) |

| Chat Widget | Dashboard |
|-------------|-----------|
| ![Chat Widget](docs/screenshots/agent_chat.png) | ![Dashboard](docs/screenshots/dashboard.png) |

| Chat Suggestions | Coupon at Checkout |
|------------------|--------------------|
| ![Chat Suggestions](docs/screenshots/chat_suggestions.png) | ![Coupon at Checkout](docs/screenshots/cart_coupon.png) |

Slack screenshots are in the [Human-in-the-Loop](#human-in-the-loop-slack) section.

---

## Features

- **User Authentication:** Register, login, logout, email verification, password reset, profile management.
- **Product Catalog:** Browse, search, and filter products by category, price, and keyword.
- **Product Details:** Detailed product pages with images, plant care info, reviews, and variations.
- **Cart & Checkout:** Add/remove products, manage variations, view cart, apply user-specific coupon codes, checkout with tax calculation.
- **Order Management:** Place orders, view order history, order details, payment via Razorpay, order confirmation emails.
- **Reviews:** Submit and update product reviews.
- **Admin Panel:** Manage users, products, categories, orders, and chat limits.
- **Modern UI:** Responsive design with Bootstrap and custom CSS.
- **AI Assistant:** Chatbot for plant care, product help, and order support (text, image, and voice), with starter suggestions in the chat.
- **Human-in-the-Loop:** Requests the AI can't handle (price matches, cancellations, refunds, damaged items, bulk orders, complaints) are escalated to the team on **Slack**, where staff approve, edit, reject, or take over the chat live.
- **Price-Match Coupons:** An approved price match creates a coupon code that only works for that customer and product.

---

## AI Agent & Workflow

### Capabilities
- **Conversational Assistant:**
  - Handles plant care queries, product recommendations, order status, and cart management (including quantities, e.g. "add 2 marigolds")
  - Supports text and image-based queries (can identify plants from images)
  - Understands casual and mixed-language messages (English/Hindi/Hinglish, typos)
  - Politely declines off-topic requests and attempts to override its instructions
  - Remembers the conversation across sessions (stored in PostgreSQL)
  - Rate-limited (max 10 AI messages per user; messages to staff during a takeover don't count)
- **Voice Features:**
  - Text-to-Speech (TTS) and Speech-to-Text (STT) using ElevenLabs
- **Agent Modules:**
  - **Supervisor Agent:** Routes each message to one sub-agent using LLM-based classification (with recent conversation as context)
  - **Cart Agent:** Add/view/remove items in cart
  - **Order Agent:** Fetch order details, order history, redirect to checkout and my orders links
  - **Research Agent:** Plant care, diseases, watering, sunlight, etc.
  - **Recommendation Agent:** Suggests products based on user needs and catalog
  - **General Agent:** Greetings, thanks, and questions about the conversation itself ("what did the team say?")
  - **Escalation Intake:** Collects the details staff need and hands the request to a human (see below)

### Simple Workflow Diagram

```mermaid
flowchart TD
    User[User Query/Input] --> Supervisor[Supervisor Agent]
    Supervisor -->|Cart| Cart[Cart Agent]
    Supervisor -->|Order| Order[Order Agent]
    Supervisor -->|Recommendation| Recommendation[Recommendation Agent]
    Supervisor -->|Research| Research[Research Agent]
    Supervisor -->|Small talk / follow-up| General[General Agent]
    Supervisor -->|Needs a human| Intake[Escalation Intake]
    Cart -- Needs Variation? --> Variation[Variation Selection]
    Variation -- After Selection --> Cart
    Intake -->|Ticket| Slack[(Slack: Plantae team)]
    Cart --> Response[Response Node]
    Order --> Response
    Recommendation --> Response
    Research --> Response
    General --> Response
    Intake --> Response
    Response --> UserResp[Final Response to User]
    User -- Image Uploaded --> PlantID[Plant Identification]
    PlantID --> Supervisor
    %% Notes:
    %% - Supervisor routes to one agent per query
    %% - Variation selection only for cart
    %% - Plant identification augments user input if image is uploaded
```

See [agent/README.md](agent/README.md) for the detailed agent and escalation architecture.

---

## Human-in-the-Loop (Slack)

When a request needs a person, the AI hands it to the Plantae team in a Slack channel instead of guessing.

### When the AI escalates
- **Price match / better deal**, **order cancellation**, **delivery issues**, **payment issues**: the AI collects the details (product, price, order number, ...), checks them against the database, and **proposes an action** for staff to approve.
- **Damaged or wrong item**, **bulk orders**, **complaints**, or when the customer **asks for a human** (or is clearly upset): the conversation is **handed over** so staff can chat with the customer directly.
- Customers can also use the **👤 Talk to a human** button or suggestion in the chat at any time.

### Two ways staff help

**1. Approve the AI's proposal (staff → AI).** A ticket card is posted to Slack with a summary, the customer's details, facts from the database, and the AI's proposal. Staff click:

| Button | What happens |
|---|---|
| **Approve** | The action is carried out (e.g. the order is cancelled) and the AI tells the customer. |
| **Edit & approve** | Staff change the proposal (e.g. 15% → 10%) and add a note; the AI tells the customer the edited outcome. |
| **Reject** | Staff give a reason; the AI explains it to the customer. Nothing is changed. |
| **Take over chat** | Switches to a live conversation (below). |

**2. Talk to the customer (staff → customer).** The AI goes quiet. The customer's messages appear in the ticket's Slack thread, and staff replies in that thread appear in the customer's chat (labelled with the staff member's name). **Hand back to AI** closes the ticket; the AI then remembers what staff said.

### Slack screenshots

<!-- Add your screenshots to docs/screenshots/ with these file names. -->

| Ticket card (AI proposal) | Edit & approve |
|---------------------------|----------------|
| ![Slack ticket card](docs/screenshots/slack_ticket_card.png) | ![Slack edit and approve](docs/screenshots/slack_edit_approve.png) |

| Live chat in a thread | Resolved ticket |
|-----------------------|-----------------|
| ![Slack takeover thread](docs/screenshots/slack_takeover_thread.png) | ![Slack resolved ticket](docs/screenshots/slack_resolved.png) |

| Customer view during takeover | Customer view after approval |
|-------------------------------|------------------------------|
| ![Chat during takeover](docs/screenshots/chat_takeover.png) | ![Chat after approval](docs/screenshots/chat_approved.png) |

### Reliability
- Tickets wait in Slack until staff act; a reminder is posted if a ticket waits longer than `HITL_SLA_MINUTES`, and after `HITL_EXPIRE_HOURS` the customer is told the team will follow up by email.
- If Slack is not configured, staff are emailed and can decide everything from the **Django admin** (Escalation Tickets), which has the same Approve / Edit / Reject / Take over / Reply actions.
- Every action is recorded on the ticket (who, when, what), visible in the admin.

---

## Price-Match Coupons

When staff approve a price match, the customer gets a coupon code such as **`ROSE10`**:

- **Only for that customer:** codes are looked up together with the logged-in account, so another customer entering `ROSE10` gets "not valid for your account".
- **Only for that product**, for **up to 2 units** per order (`PRICE_MATCH_MAX_UNITS`).
- **Valid for 7 days** (`PRICE_MATCH_VALID_DAYS`) and **single use**: it is marked used only after Razorpay confirms the payment.
- The customer enters it in the **coupon box on the cart or checkout page**; the discount is shown before tax (18% GST is charged on the discounted amount) and saved on the order.
- Coupons are listed in the admin (owner, product, %, expiry, when used, order, and the ticket that created it).

---

## App Structure

### 1. Accounts
Handles user authentication, registration, profile management, and user dashboard.
- Custom user model (`Account`) with email as the username.
- User registration, login, logout, and email activation.
- User profile management (`UserProfile`), including address and profile picture.
- Password reset and change, user dashboard, and context processor for user info.

### 2. Agent
AI-powered chat assistant for plant care, shopping, and order support.
- Chat interface for users to interact with the AI assistant.
- Handles plant identification from images using LLMs.
- Supports cart, order, product recommendation, and plant care queries.
- Voice integration (STT/TTS), conversation memory (PostgreSQL), and rate limiting.
- Human-in-the-loop escalations to Slack, with a background worker for notifications and follow-ups.
- Admin tools for chat history, agent errors, and escalation tickets.
- See [Detailed Agent Workflow Diagram](agent/README.md#detailed-agent-workflow-diagram) for advanced logic.

### 3. Carts
Manages shopping cart functionality for users (both authenticated and guests).
- Add, remove, and update products in the cart.
- Handles product variations (color, size, etc.).
- Calculates cart totals, coupon discount, tax, and grand total in one place (`carts/pricing.py`).
- User-specific coupon codes (`Coupon`), created from approved price matches.
- Checkout process integration and cart item count context processor.

### 4. Category
Manages product categories for the store.
- CRUD for product categories (name, slug, description, image).
- Used for filtering and organizing products in the store.
- Context processor for category navigation.

### 5. Orders
Handles order placement, payment, and order history.
- Place orders from cart items, payment via Razorpay.
- Stores order details, shipping address, payment info, and any coupon discount.
- Order status tracking, order history, and order detail views.
- Sends order confirmation emails.

### 6. Store
Manages products, product variations, reviews, and the main store interface.
- Product listing, detail, and search.
- Product variations (color, size, pack), reviews, and gallery images.
- Plant care information for products.
- Pagination and price filtering.

---

## Tech Stack

- **Backend:** Django 4.2 (Python)
- **Frontend:** Django Templates, Bootstrap, jQuery, FontAwesome
- **AI/Agent:** LangChain, OpenAI, LangGraph (PostgreSQL checkpointer), ElevenLabs (TTS/STT)
- **Human-in-the-Loop:** Slack (Block Kit buttons, threads, signed webhooks), django-q2 background worker
- **LLM:** OpenAI's gpt-5.6-luna
- **Database:** Azure Database for PostgreSQL Flexible Server
- **Payments:** Razorpay
- **Other:** dotenv, crispy-forms, admin-thumbnails, etc.

See [`requirements.txt`](requirements.txt) for full dependency list.

---

## Getting Started

1. **Clone the repo:**
   ```bash
   git clone https://github.com/ayushraj09/plantae.git
   cd plantae
   ```
2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```
3. **Set up environment variables:**
   - Copy `.env-sample` to `.env` and fill in your secrets.
4. **Run migrations and set up agent memory tables:**
   ```bash
   python manage.py migrate
   python manage.py setup_checkpointer
   ```
5. **Create superuser:**
   ```bash
   python manage.py createsuperuser
   ```
6. **Run the server and the background worker** (two terminals):
   ```bash
   python manage.py runserver
   python manage.py qcluster
   ```
   The worker posts tickets to Slack, writes the AI's reply after staff decide, and sends reminders.
   Slack is optional for local development; without it, tickets are handled from the admin.
7. **Access:**
   - Website: [http://127.0.0.1:8000/](http://127.0.0.1:8000/)
   - Admin: [http://127.0.0.1:8000/admin/](http://127.0.0.1:8000/admin/)

---

## Load Test Analysis

Load testing was performed with Locust using the scenario in [`locust_loadtest/locustfile.py`](locust_loadtest/locustfile.py). The suite mixes three weighted user types against production: anonymous browsers (weight 4), authenticated customers who log in and exercise cart/checkout paths (weight 3), and a cart-profiling user that hammers `add_cart` (weight 1). Each page load also fetches its referenced static and media assets, mirroring real browser traffic.

### Test Coverage

- **Anonymous browse:** `GET /`, `/store/`, `/store/category/plants/`, `/store/search/`, product detail pages
- **Authenticated journey:** login, dashboard, my orders, browse, `POST /cart/add_cart/{id}/`, cart view, checkout page
- **Cart profiling:** repeated `POST /cart/add_cart/{id}/`, cart and checkout reads
- **Static/media:** up to 12 referenced assets per page (`/static/…`, `/media/…`)

Order-placement POSTs were left disabled in both runs so no test orders were written to the production database.

### Run 1 — Baseline (50 users)

50 concurrent users, spawn rate 5/s, 3-minute run.

| Metric | Result |
|--------|--------|
| Peak users | 50 |
| Total requests | 8,351 |
| Total failures | 5 |
| Failure rate | 0.06% |
| Average throughput | 46.7 requests/second |
| Aggregate median response time | 44 ms |
| Aggregate 95th percentile | 3,300 ms |
| Aggregate 99th percentile | 6,200 ms |
| Maximum response time | 7,597 ms |

The aggregate median is dominated by the ~7,400 static/media requests, which Apache served in 42-43 ms. Dynamic Django views told a very different story:

- **Static and media assets held up well:** 42-43 ms median across all asset types, 95th percentile between 55 and 360 ms, zero failures.
- **Dynamic pages degraded:** home, store, category, product detail, and search all sat at a 2,800-3,000 ms median. Authenticated dashboard and my-orders pages were 2,600-2,700 ms. Login POST was 2,000 ms.
- **Cart writes were the worst path:** `POST /cart/add_cart/{id}/` had a 6,000-6,200 ms median, roughly 2x any read path.
- **5 failures:** four `RemoteDisconnected` errors and one `403` from a stale CSRF token on a retried cart-add POST.

### Run 2 — Stress (200 users)

200 concurrent users, spawn rate 10/s, 3-minute run.

| Metric | Result |
|--------|--------|
| Peak users | 200 |
| Total requests | 11,209 |
| Total failures | 591 |
| Failure rate | 5.27% |
| Average throughput | 62.6 requests/second |
| Aggregate median response time | 52 ms |
| Aggregate 90th percentile | 12,000 ms |
| Aggregate 99th percentile | 19,000 ms |
| Maximum response time | 30,880 ms |

Quadrupling the user count barely moved throughput (46.7 → 62.6 req/s) while latency and errors collapsed:

- **Dynamic pages:** ~13,000 ms median across every browse and account view.
- **Cart writes:** 25,000-31,000 ms median on `add_cart` POSTs.
- **Responses capped near 31 s**, indicating a proxy/Gunicorn timeout ceiling rather than eventual completion.
- **591 failures (5.27%):** mostly `RemoteDisconnected` as the server dropped connections; the auth path itself began failing (23 failed logins, 10 unreachable dashboards), and CSRF-dependent cart POSTs 403'd because the page that carries the token never loaded.

### Run 3 — Anonymous-only capacity sweep

Anonymous browse journey only (no login), 90 s per level, spawn rate 20/s.

| Concurrent users | Failure rate | Successful requests |
|--------|--------|--------|
| 100 | 0.43% | 99.57% |
| 150 | 0.63% | 99.37% |
| 200 | 17.24% | 82.76% |
| 250 | 23.03% | 76.97% |
| 500 | 27.28% | 72.72% |

**~150 concurrent unauthenticated users** is the ceiling for a healthy service (>99% success). Between 150 and 200 the site falls off a cliff as Gunicorn's queue overflows and connections are dropped; past 250, throughput drops while errors climb.

### Conclusion

The server handles **~150 concurrent unauthenticated browsers** or **~50 concurrent authenticated customers** before failures climb. Dynamic Django throughput is capped at **~15-20 requests/second** regardless of load — consistent with a small Gunicorn worker pool where each database-writing request holds a worker for seconds. Beyond those limits, added concurrency produces queueing and timeouts, not more work done. The bottleneck is not the network: static assets from the same host returned in ~43 ms across every run.

Raw Locust result files are in [`locust_loadtest/`](locust_loadtest/) (`plantae_loadtest_*` for the baseline, `plantae_stress_*` for the stress run), with full HTML reports at [`plantae_loadtest_report.html`](locust_loadtest/plantae_loadtest_report.html) and [`plantae_stress_report.html`](locust_loadtest/plantae_stress_report.html).

---

## Deployment

- **Production:** Azure VM with Docker Compose, deployed by GitHub Actions on every push to `main` (`deploy.sh`).
- **Domain:** [https://plantaeai.tech](https://plantaeai.tech)
- **Containers:**
  - `web` (`plantae`): runs migrations, `setup_checkpointer`, `collectstatic`, then Gunicorn.
  - `worker` (`plantae-worker`): `python manage.py qcluster` for Slack notifications, AI replies after staff decisions, and SLA reminders.
- **Static & Media:** Collected into `static/` and served by Apache; the chat widget's CSS/JS URLs carry `CHAT_WIDGET_VERSION` so browsers fetch new versions after a deploy.
- **Database:** Azure Database for PostgreSQL (also stores agent memory and the background task queue).

### Configuration

Copy `.env-sample` to `.env`. Settings added for the agent and human-in-the-loop:

| Variable | Purpose |
|---|---|
| `SLACK_BOT_TOKEN`, `SLACK_SIGNING_SECRET`, `SLACK_ESCALATION_CHANNEL` | Slack app credentials and the channel for tickets |
| `HITL_STAFF_EMAILS` | Email fallback and overdue reminders (comma-separated) |
| `HITL_SLA_MINUTES`, `HITL_EXPIRE_HOURS` | When to remind staff, and when to close unanswered tickets |
| `PRICE_MATCH_MAX_UNITS`, `PRICE_MATCH_VALID_DAYS` | Coupon limits (default 2 units, 7 days) |
| `SITE_URL` | Public URL used in links from Slack/email |
| `CHAT_WIDGET_VERSION` | Bump when the chat widget's CSS/JS change |
| `DB_SSLMODE` | Database SSL mode (default `require`) |

### Slack app setup
1. Create a Slack app with bot scopes `chat:write`, `users:read`, `users:read.email`, `channels:history` (and `groups:history` for a private channel), install it, and invite it to the escalation channel.
2. **Interactivity** request URL: `https://<your-domain>/agent/slack/interactions/`
3. **Event Subscriptions** request URL: `https://<your-domain>/agent/slack/events/`, subscribed to `message.channels` (or `message.groups`).
4. Staff are matched to site accounts by email; give their accounts `is_staff` so decisions are recorded under their name.

---

## License

This project is licensed under the [MIT License](LICENSE).

---

## Contact

- **Email:** ayush.ttps@gmail.com

---

> _Pull requests are welcome! Please open an issue first to discuss changes._ 
