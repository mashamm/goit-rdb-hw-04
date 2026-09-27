"""Збирає notebooks/hw4_olist.ipynb."""
import json
import pathlib

import nbformat as nbf

ROOT = pathlib.Path(__file__).resolve().parents[1]
I = json.loads((ROOT / "tools/interpretations.json").read_text(encoding="utf-8"))

cells = []
md = lambda s: cells.append(nbf.v4.new_markdown_cell(s.strip()))
code = lambda s: cells.append(nbf.v4.new_code_cell(s.strip()))


def query(sql_text):
    code(f'q("""\n{sql_text.strip()}\n""")')


def dml(sql_text, show=10):
    code(f'res = dml("""\n{sql_text.strip()}\n""")\nprint("RETURNING rows:", len(res))\nres.head({show})')


def ddl(sql_text):
    code(f'run("""\n{sql_text.strip()}\n""")\nprint("OK")')


def block(qid, question, sql_text):
    md(f"### {qid}\n\n**Business-question:** {question}")
    query(sql_text)
    md(f"**Interpretation:** {I[qid]}")


md("""
# ДЗ 4. Olist: typed-схема, DML з PostgreSQL-фічами, JOIN, агрегати, set operations і window functions

**Студентка:** Samoilenko Mariia

**Датасет:** [Brazilian E-Commerce Public Dataset by Olist](https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce) (Kaggle, CC BY-NC-SA 4.0).
Використано 6 CSV: customers, orders, order_items, products, sellers, order_reviews.
""")

# ------------------------------------------------------------------ 1
md("## Завдання 1. Setup і typed-схема Olist")
code('''
import glob
import os
import subprocess
import sys


def pip_install(*args):
    subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", *args])


pip_install("psycopg2-binary", "sqlalchemy", "pandas", "kagglehub", "fasteners", "platformdirs", "psutil")

# pgserver 0.1.4 має wheel-файли лише до cp312; його розширення зібране в abi3,
# тому на новішому Python (Colab) встановлюємо cp312-wheel з тегом abi3.
if sys.version_info < (3, 13):
    pip_install("pgserver==0.1.4")
else:
    wheel_dir = "/tmp/pgserver_wheel"
    subprocess.check_call([
        sys.executable, "-m", "pip", "download", "-q", "pgserver==0.1.4",
        "--no-deps", "--only-binary=:all:", "--python-version", "3.12", "-d", wheel_dir,
    ])
    for whl in glob.glob(f"{wheel_dir}/pgserver-0.1.4-cp312-cp312-*.whl"):
        os.replace(whl, whl.replace("-cp312-cp312-", "-cp312-abi3-"))
    pip_install("--no-deps", *glob.glob(f"{wheel_dir}/pgserver-0.1.4-cp312-abi3-*.whl"))
''')
code('''
import pandas as pd
import pgserver
from sqlalchemy import create_engine, text

pd.set_option("display.max_columns", 30)
pd.set_option("display.width", 200)
pd.set_option("display.max_colwidth", 80)

pg = pgserver.get_server("/tmp/hw4_pg", cleanup_mode="stop")
engine = create_engine(pg.get_uri().replace("postgresql://", "postgresql+psycopg2://", 1), future=True)

with engine.connect() as conn:
    print(conn.execute(text("SELECT version()")).scalar_one())


def q(sql_text):
    """SELECT → DataFrame."""
    return pd.read_sql(text(sql_text), engine)


def run(sql_text):
    """DDL / DML без результату в одній транзакції."""
    with engine.begin() as conn:
        conn.execute(text(sql_text))


def dml(sql_text):
    """DML з RETURNING в одній транзакції → DataFrame повернутих рядків."""
    with engine.begin() as conn:
        result = conn.execute(text(sql_text))
        return pd.DataFrame(result.fetchall(), columns=list(result.keys()))
''')
md("""
### Отримання CSV

Варіант A — KaggleHub (публічний датасет завантажується і без облікових даних).
Варіант B — копія 6 потрібних CSV у репозиторії (`data/olist/`), якщо KaggleHub недоступний.
""")
code('''
FILES = {
    "olist_customers_raw": "olist_customers_dataset.csv",
    "olist_orders_raw": "olist_orders_dataset.csv",
    "olist_order_items_raw": "olist_order_items_dataset.csv",
    "olist_products_raw": "olist_products_dataset.csv",
    "olist_sellers_raw": "olist_sellers_dataset.csv",
    "olist_order_reviews_raw": "olist_order_reviews_dataset.csv",
}
REPO_RAW = "https://raw.githubusercontent.com/mashamm/goit-rdb-hw-04/main/data/olist"

try:
    import kagglehub
    dataset_dir = kagglehub.dataset_download("olistbr/brazilian-ecommerce")
    print("Варіант A (KaggleHub):", dataset_dir)
except Exception as exc:
    print("KaggleHub недоступний:", exc)
    dataset_dir = os.path.abspath("../data/olist")
    if not all(os.path.exists(os.path.join(dataset_dir, f)) for f in FILES.values()):
        from urllib.request import urlretrieve
        dataset_dir = "/content/data/olist" if os.path.isdir("/content") else os.path.abspath("data/olist")
        os.makedirs(dataset_dir, exist_ok=True)
        for f in FILES.values():
            urlretrieve(f"{REPO_RAW}/{f}", os.path.join(dataset_dir, f))
    print("Варіант B (CSV з репозиторію):", dataset_dir)
''')
md("### Raw-шар: CSV → `*_raw` таблиці (проміжний шар без constraints)")
code('''
run("DROP TABLE IF EXISTS olist_customers CASCADE; DROP TABLE IF EXISTS olist_orders CASCADE;")

raw_counts = {}
for table_name, file_name in FILES.items():
    df = pd.read_csv(os.path.join(dataset_dir, file_name))
    df.to_sql(table_name, engine, if_exists="replace", index=False, chunksize=10_000)
    raw_counts[table_name] = len(df)
    print(f"{table_name:26s} {df.shape}")
''')
md("### Typed-схема")
ddl("""
DROP TABLE IF EXISTS customer_segments    CASCADE;
DROP TABLE IF EXISTS seller_score         CASCADE;
DROP TABLE IF EXISTS seller_alerts        CASCADE;
DROP TABLE IF EXISTS olist_customer_dim   CASCADE;
DROP TABLE IF EXISTS olist_order_reviews  CASCADE;
DROP TABLE IF EXISTS olist_order_items    CASCADE;
DROP TABLE IF EXISTS olist_orders         CASCADE;
DROP TABLE IF EXISTS olist_customers      CASCADE;
DROP TABLE IF EXISTS olist_products       CASCADE;
DROP TABLE IF EXISTS olist_sellers        CASCADE;

CREATE TABLE olist_customers (
    customer_id              TEXT PRIMARY KEY,
    customer_unique_id       TEXT NOT NULL,
    customer_zip_code_prefix INTEGER,
    customer_city            TEXT,
    customer_state           CHAR(2) NOT NULL
);

CREATE INDEX idx_olist_customers_unique_id
    ON olist_customers (customer_unique_id);

CREATE TABLE olist_orders (
    order_id                      TEXT PRIMARY KEY,
    customer_id                   TEXT NOT NULL REFERENCES olist_customers(customer_id),
    order_status                  TEXT NOT NULL,
    order_purchase_timestamp      TIMESTAMP NOT NULL,
    order_approved_at             TIMESTAMP,
    order_delivered_carrier_date  TIMESTAMP,
    order_delivered_customer_date TIMESTAMP,
    order_estimated_delivery_date TIMESTAMP,
    CHECK (order_status IN (
        'created', 'approved', 'invoiced', 'processing',
        'shipped', 'delivered', 'unavailable', 'canceled'
    ))
);

CREATE TABLE olist_products (
    product_id                 TEXT PRIMARY KEY,
    product_category_name      TEXT,
    product_name_length        INTEGER CHECK (product_name_length IS NULL OR product_name_length >= 0),
    product_description_length INTEGER CHECK (product_description_length IS NULL OR product_description_length >= 0),
    product_photos_qty         INTEGER CHECK (product_photos_qty IS NULL OR product_photos_qty >= 0),
    product_weight_g           INTEGER CHECK (product_weight_g IS NULL OR product_weight_g >= 0),
    product_length_cm          INTEGER CHECK (product_length_cm IS NULL OR product_length_cm >= 0),
    product_height_cm          INTEGER CHECK (product_height_cm IS NULL OR product_height_cm >= 0),
    product_width_cm           INTEGER CHECK (product_width_cm IS NULL OR product_width_cm >= 0)
);

CREATE TABLE olist_sellers (
    seller_id              TEXT PRIMARY KEY,
    seller_zip_code_prefix INTEGER,
    seller_city            TEXT,
    seller_state           CHAR(2) NOT NULL
);

CREATE TABLE olist_order_items (
    order_id            TEXT NOT NULL REFERENCES olist_orders(order_id),
    order_item_id       INTEGER NOT NULL,
    product_id          TEXT REFERENCES olist_products(product_id),
    seller_id           TEXT REFERENCES olist_sellers(seller_id),
    shipping_limit_date TIMESTAMP,
    price               NUMERIC(12, 2) CHECK (price IS NULL OR price >= 0),
    freight_value       NUMERIC(12, 2) CHECK (freight_value IS NULL OR freight_value >= 0),
    PRIMARY KEY (order_id, order_item_id)
);

CREATE INDEX idx_olist_order_items_seller_order
    ON olist_order_items (seller_id, order_id);

CREATE TABLE olist_order_reviews (
    review_row_id            BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    review_id                TEXT,
    order_id                 TEXT NOT NULL REFERENCES olist_orders(order_id),
    review_score             SMALLINT CHECK (review_score BETWEEN 1 AND 5),
    review_comment_title     TEXT,
    review_comment_message   TEXT,
    review_creation_date     TIMESTAMP,
    review_answer_timestamp  TIMESTAMP
);

CREATE INDEX idx_olist_order_reviews_order_id
    ON olist_order_reviews (order_id);
""")
md("### Raw → typed через `INSERT ... SELECT`\n\nУ сирому CSV колонки названі з помилкою `product_name_lenght` / `product_description_lenght`; у typed-схемі вони нормалізовані.")
ddl("""
INSERT INTO olist_customers
SELECT customer_id, customer_unique_id, customer_zip_code_prefix::INTEGER,
       customer_city, customer_state::CHAR(2)
FROM olist_customers_raw;

INSERT INTO olist_orders
SELECT order_id, customer_id, order_status,
       order_purchase_timestamp::TIMESTAMP,
       order_approved_at::TIMESTAMP,
       order_delivered_carrier_date::TIMESTAMP,
       order_delivered_customer_date::TIMESTAMP,
       order_estimated_delivery_date::TIMESTAMP
FROM olist_orders_raw;

INSERT INTO olist_products
SELECT product_id, product_category_name,
       product_name_lenght::INTEGER, product_description_lenght::INTEGER,
       product_photos_qty::INTEGER, product_weight_g::INTEGER,
       product_length_cm::INTEGER, product_height_cm::INTEGER, product_width_cm::INTEGER
FROM olist_products_raw;

INSERT INTO olist_sellers
SELECT seller_id, seller_zip_code_prefix::INTEGER, seller_city, seller_state::CHAR(2)
FROM olist_sellers_raw;

INSERT INTO olist_order_items
SELECT order_id, order_item_id::INTEGER, product_id, seller_id,
       shipping_limit_date::TIMESTAMP, price::NUMERIC(12, 2), freight_value::NUMERIC(12, 2)
FROM olist_order_items_raw;

INSERT INTO olist_order_reviews (
    review_id, order_id, review_score, review_comment_title,
    review_comment_message, review_creation_date, review_answer_timestamp
)
SELECT review_id, order_id, review_score::SMALLINT, review_comment_title,
       review_comment_message, review_creation_date::TIMESTAMP, review_answer_timestamp::TIMESTAMP
FROM olist_order_reviews_raw;
""")
md("### Smoke-test: typed vs raw")
code('''
typed = q("""
SELECT 'customers' AS table_name, COUNT(*) AS n_rows FROM olist_customers
UNION ALL SELECT 'orders', COUNT(*) FROM olist_orders
UNION ALL SELECT 'order_items', COUNT(*) FROM olist_order_items
UNION ALL SELECT 'products', COUNT(*) FROM olist_products
UNION ALL SELECT 'sellers', COUNT(*) FROM olist_sellers
UNION ALL SELECT 'reviews', COUNT(*) FROM olist_order_reviews
ORDER BY table_name
""")
typed["raw_rows"] = typed["table_name"].map({
    "customers": raw_counts["olist_customers_raw"],
    "orders": raw_counts["olist_orders_raw"],
    "order_items": raw_counts["olist_order_items_raw"],
    "products": raw_counts["olist_products_raw"],
    "sellers": raw_counts["olist_sellers_raw"],
    "reviews": raw_counts["olist_order_reviews_raw"],
})
typed["lost_rows"] = typed["raw_rows"] - typed["n_rows"]
typed
''')
md(I["1"])

# ------------------------------------------------------------------ 2
md("## Завдання 2. DML-запити з PostgreSQL-фічами\n\n### 2.1. `INSERT ... RETURNING`: alert для продавця з найбільшою кількістю запізнень")
ddl("""
DROP TABLE IF EXISTS seller_alerts CASCADE;

CREATE TABLE seller_alerts (
    alert_id   BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    seller_id  TEXT NOT NULL REFERENCES olist_sellers(seller_id),
    alert_type TEXT NOT NULL CHECK (alert_type IN ('late_delivery', 'low_rating', 'data_quality')),
    severity   SMALLINT NOT NULL CHECK (severity BETWEEN 1 AND 5),
    details    TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")
dml("""
WITH seller_orders AS (
    SELECT DISTINCT oi.seller_id, oi.order_id
    FROM olist_order_items AS oi
),
late_sellers AS (
    SELECT so.seller_id, COUNT(DISTINCT o.order_id) AS late_orders
    FROM seller_orders AS so
    JOIN olist_orders AS o ON o.order_id = so.order_id
    WHERE o.order_delivered_customer_date IS NOT NULL
      AND o.order_estimated_delivery_date IS NOT NULL
      AND o.order_delivered_customer_date::DATE > o.order_estimated_delivery_date::DATE
    GROUP BY so.seller_id
    ORDER BY late_orders DESC, so.seller_id
    LIMIT 1
)
INSERT INTO seller_alerts (seller_id, alert_type, severity, details)
SELECT seller_id, 'late_delivery', 4,
       'Seller has ' || late_orders || ' late delivered orders in the loaded dataset'
FROM late_sellers
RETURNING alert_id, seller_id, alert_type, severity, details, created_at
""")
md(I["2.1"])

md("### 2.2. `INSERT ... ON CONFLICT DO UPDATE`: idempotent upsert `seller_score`")
ddl("""
DROP TABLE IF EXISTS seller_score CASCADE;

CREATE TABLE seller_score (
    seller_id   TEXT PRIMARY KEY REFERENCES olist_sellers(seller_id),
    avg_rating  NUMERIC(3, 2),
    n_reviews   INTEGER NOT NULL DEFAULT 0 CHECK (n_reviews >= 0),
    tier        TEXT CHECK (tier IN ('gold', 'silver', 'bronze')),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
""")
SELLER_SCORE = """
WITH seller_orders AS (
    SELECT DISTINCT oi.seller_id, oi.order_id
    FROM olist_order_items AS oi
),
review_per_order AS (
    SELECT rv.order_id, AVG(rv.review_score)::NUMERIC(3, 2) AS order_review_score
    FROM olist_order_reviews AS rv
    WHERE rv.review_score IS NOT NULL
    GROUP BY rv.order_id
),
seller_rating AS (
    SELECT so.seller_id,
           AVG(rpo.order_review_score)::NUMERIC(3, 2) AS avg_rating,
           COUNT(rpo.order_id) AS n_reviews
    FROM seller_orders AS so
    LEFT JOIN review_per_order AS rpo ON rpo.order_id = so.order_id
    GROUP BY so.seller_id
)
INSERT INTO seller_score (seller_id, avg_rating, n_reviews, tier)
SELECT seller_id, avg_rating, n_reviews,
       CASE
           WHEN avg_rating IS NULL THEN NULL
           WHEN avg_rating >= 4.5 THEN 'gold'
           WHEN avg_rating >= 3.5 THEN 'silver'
           ELSE 'bronze'
       END AS tier
FROM seller_rating
ON CONFLICT (seller_id) DO UPDATE
SET avg_rating = EXCLUDED.avg_rating,
    n_reviews  = EXCLUDED.n_reviews,
    tier       = EXCLUDED.tier,
    updated_at = NOW()
RETURNING seller_id, avg_rating, n_reviews, tier, updated_at
"""
dml(SELLER_SCORE)
md("**Перевірка ідемпотентності:** запускаємо той самий upsert удруге — кількість рядків у `seller_score` не змінюється.")
code(f'''
before = q("SELECT COUNT(*) AS n FROM seller_score")["n"][0]
res = dml("""{SELLER_SCORE.strip()}""")
after = q("SELECT COUNT(*) AS n FROM seller_score")["n"][0]
print(f"рядків до: {{before}}, після повторного запуску: {{after}}, оновлено через ON CONFLICT: {{len(res)}}")
assert before == after
q("""
SELECT COALESCE(tier, '(no reviews)') AS tier, COUNT(*) AS n_sellers,
       ROUND(AVG(avg_rating), 2) AS avg_rating, SUM(n_reviews) AS reviews
FROM seller_score
GROUP BY tier
ORDER BY n_sellers DESC
""")
''')
md(I["2.2"])

md("### 2.3. `UPDATE ... FROM`: прапорець запізнення `is_late`")
ddl("""
ALTER TABLE olist_orders
    ADD COLUMN IF NOT EXISTS is_late BOOLEAN NOT NULL DEFAULT FALSE;
""")
dml("""
WITH delivery_flags AS (
    SELECT order_id,
           (order_delivered_customer_date IS NOT NULL
            AND order_estimated_delivery_date IS NOT NULL
            AND order_delivered_customer_date::DATE > order_estimated_delivery_date::DATE) AS is_late_calc
    FROM olist_orders
)
UPDATE olist_orders AS o
SET is_late = f.is_late_calc
FROM delivery_flags AS f
WHERE f.order_id = o.order_id
RETURNING o.order_id, o.customer_id, o.is_late
""")
query("""
SELECT is_late, COUNT(*) AS n_orders, ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct
FROM olist_orders
GROUP BY is_late
ORDER BY is_late
""")
md(I["2.3"])

md("### 2.4. `DELETE ... RETURNING`: видалення застарілих alert-ів")
dml("""
DELETE FROM seller_alerts
WHERE created_at < NOW() - INTERVAL '30 days'
RETURNING alert_id, seller_id, alert_type, created_at
""")
md(I["2.4a"])
dml("""
INSERT INTO seller_alerts (seller_id, alert_type, severity, details, created_at)
SELECT seller_id, 'data_quality', 2, 'Test alert backdated by 45 days', NOW() - INTERVAL '45 days'
FROM seller_score
ORDER BY seller_id
LIMIT 1
RETURNING alert_id, seller_id, alert_type, created_at
""")
dml("""
DELETE FROM seller_alerts
WHERE created_at < NOW() - INTERVAL '30 days'
RETURNING alert_id, seller_id, alert_type, created_at
""")
md(I["2.4b"])

# ------------------------------------------------------------------ 3
md("## Завдання 3. `customer_segments`\n\n### Дедуплікований customer dimension")
ddl("""
DROP TABLE IF EXISTS customer_segments CASCADE;
DROP TABLE IF EXISTS olist_customer_dim CASCADE;

CREATE TABLE olist_customer_dim (
    customer_unique_id TEXT PRIMARY KEY,
    latest_customer_id TEXT REFERENCES olist_customers(customer_id),
    customer_state     CHAR(2),
    customer_city      TEXT
);

INSERT INTO olist_customer_dim (customer_unique_id, latest_customer_id, customer_state, customer_city)
SELECT DISTINCT ON (c.customer_unique_id)
    c.customer_unique_id, c.customer_id, c.customer_state, c.customer_city
FROM olist_customers AS c
LEFT JOIN olist_orders AS o ON o.customer_id = c.customer_id
ORDER BY c.customer_unique_id, o.order_purchase_timestamp DESC NULLS LAST, c.customer_id;
""")
query("""
SELECT
    (SELECT COUNT(*) FROM olist_customers)    AS customer_ids,
    (SELECT COUNT(*) FROM olist_customer_dim) AS unique_customers
""")
md("### DDL і idempotent-наповнення")
ddl("""
CREATE TABLE customer_segments (
    segment_id          BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_unique_id  TEXT NOT NULL,
    segment_name        TEXT NOT NULL CHECK (segment_name IN ('VIP', 'regular', 'new', 'inactive')),
    rfm_score           SMALLINT NOT NULL CHECK (rfm_score BETWEEN 1 AND 5),
    recency_days        INTEGER CHECK (recency_days IS NULL OR recency_days >= 0),
    monetary_value      NUMERIC(12, 2) NOT NULL DEFAULT 0 CHECK (monetary_value >= 0),
    n_orders            INTEGER NOT NULL DEFAULT 0 CHECK (n_orders >= 0),
    assigned_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (customer_unique_id)
);

ALTER TABLE customer_segments
    ADD CONSTRAINT fk_customer_segments_customer_unique
    FOREIGN KEY (customer_unique_id)
    REFERENCES olist_customer_dim(customer_unique_id)
    ON DELETE CASCADE;
""")
SEGMENTS = """
WITH reference_date AS (
    SELECT (MAX(order_purchase_timestamp)::DATE + 1) AS as_of_date
    FROM olist_orders
),
order_totals AS (
    SELECT o.order_id, o.customer_id, o.order_purchase_timestamp::DATE AS order_date,
           COALESCE(SUM(oi.price + oi.freight_value), 0)::NUMERIC(12, 2) AS order_total
    FROM olist_orders AS o
    LEFT JOIN olist_order_items AS oi ON oi.order_id = o.order_id
    GROUP BY o.order_id, o.customer_id, o.order_purchase_timestamp
),
customer_stats AS (
    SELECT c.customer_unique_id,
           COUNT(DISTINCT ot.order_id) AS n_orders,
           COALESCE(SUM(ot.order_total), 0)::NUMERIC(12, 2) AS monetary_value,
           MAX(ot.order_date) AS last_order_date
    FROM olist_customer_dim AS cd
    JOIN olist_customers AS c ON c.customer_unique_id = cd.customer_unique_id
    LEFT JOIN order_totals AS ot ON ot.customer_id = c.customer_id
    GROUP BY c.customer_unique_id
),
segmented AS (
    SELECT cs.customer_unique_id, cs.n_orders, cs.monetary_value,
           CASE WHEN cs.last_order_date IS NULL THEN NULL
                ELSE (rd.as_of_date - cs.last_order_date)::INTEGER END AS recency_days,
           CASE
               WHEN cs.monetary_value >= 1000 THEN 'VIP'
               WHEN cs.last_order_date IS NOT NULL
                    AND (rd.as_of_date - cs.last_order_date)::INTEGER <= 90
                    AND cs.n_orders = 1 THEN 'new'
               WHEN cs.n_orders >= 2 OR cs.monetary_value >= 100 THEN 'regular'
               ELSE 'inactive'
           END AS segment_name,
           CASE
               WHEN cs.monetary_value >= 1000 THEN 5
               WHEN cs.monetary_value >= 500  THEN 4
               WHEN cs.n_orders >= 2          THEN 3
               WHEN cs.n_orders = 1           THEN 2
               ELSE 1
           END::SMALLINT AS rfm_score
    FROM customer_stats AS cs
    CROSS JOIN reference_date AS rd
)
INSERT INTO customer_segments (customer_unique_id, segment_name, rfm_score, recency_days, monetary_value, n_orders)
SELECT customer_unique_id, segment_name, rfm_score, recency_days, monetary_value, n_orders
FROM segmented
ON CONFLICT (customer_unique_id) DO UPDATE
SET segment_name   = EXCLUDED.segment_name,
    rfm_score      = EXCLUDED.rfm_score,
    recency_days   = EXCLUDED.recency_days,
    monetary_value = EXCLUDED.monetary_value,
    n_orders       = EXCLUDED.n_orders,
    assigned_at    = NOW()
RETURNING customer_unique_id, segment_name, rfm_score, recency_days, monetary_value, n_orders
"""
dml(SEGMENTS)
md("Повторний запуск (idempotency) і розподіл сегментів:")
code(f'''
res = dml("""{SEGMENTS.strip()}""")
print("повторний upsert оновив рядків:", len(res))
q("""
SELECT segment_name, COUNT(*) AS n_customers,
       ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) AS pct,
       ROUND(AVG(monetary_value), 2) AS avg_monetary,
       ROUND(AVG(n_orders), 2) AS avg_orders
FROM customer_segments
GROUP BY segment_name
ORDER BY n_customers DESC
""")
''')
md("Перевірка constraints:")
query("""
SELECT conname, contype, pg_get_constraintdef(oid) AS definition
FROM pg_constraint
WHERE conrelid = 'customer_segments'::regclass
ORDER BY conname
""")
md(I["3"])

# ------------------------------------------------------------------ 4
md("## Завдання 4. JOIN-запити з business-interpretation")
block("4.1. INNER JOIN (4 таблиці)", "Які категорії товарів і штати продавців дають найбільший revenue у delivered-замовленнях?", """
SELECT p.product_category_name, s.seller_state,
       COUNT(DISTINCT oi.order_id) AS n_orders,
       SUM(oi.price + oi.freight_value)::NUMERIC(12, 2) AS revenue
FROM olist_order_items AS oi
JOIN olist_orders   AS o ON o.order_id   = oi.order_id
JOIN olist_products AS p ON p.product_id = oi.product_id
JOIN olist_sellers  AS s ON s.seller_id  = oi.seller_id
WHERE o.order_status = 'delivered'
GROUP BY p.product_category_name, s.seller_state
ORDER BY revenue DESC NULLS LAST
LIMIT 10
""")
block("4.2. LEFT JOIN + COALESCE", "Які customer-level features можна побудувати для реального покупця на рівні customer_unique_id?", """
WITH order_totals AS (
    SELECT o.order_id, c.customer_unique_id,
           SUM(oi.price + oi.freight_value)::NUMERIC(12, 2) AS order_total
    FROM olist_orders AS o
    JOIN olist_customers AS c ON c.customer_id = o.customer_id
    LEFT JOIN olist_order_items AS oi ON oi.order_id = o.order_id
    GROUP BY o.order_id, c.customer_unique_id
),
review_per_order AS (
    SELECT rv.order_id, AVG(rv.review_score)::NUMERIC(3, 2) AS order_review_score
    FROM olist_order_reviews AS rv
    WHERE rv.review_score IS NOT NULL
    GROUP BY rv.order_id
),
customer_stats AS (
    SELECT ot.customer_unique_id,
           COUNT(DISTINCT ot.order_id) AS n_orders,
           COALESCE(SUM(ot.order_total), 0)::NUMERIC(12, 2) AS total_spend,
           AVG(rpo.order_review_score)::NUMERIC(3, 2) AS avg_review_score
    FROM order_totals AS ot
    LEFT JOIN review_per_order AS rpo ON rpo.order_id = ot.order_id
    GROUP BY ot.customer_unique_id
)
SELECT cd.customer_unique_id, cd.customer_state,
       COALESCE(cs.n_orders, 0) AS n_orders,
       COALESCE(cs.total_spend, 0)::NUMERIC(12, 2) AS total_spend,
       COALESCE(cs.avg_review_score, 0)::NUMERIC(3, 2) AS avg_review_score
FROM olist_customer_dim AS cd
LEFT JOIN customer_stats AS cs ON cs.customer_unique_id = cd.customer_unique_id
ORDER BY total_spend DESC NULLS LAST
LIMIT 20
""")
block("4.3. FULL OUTER JOIN", "Які штати представлені тільки серед клієнтів, тільки серед продавців або в обох групах?", """
WITH customer_states AS (
    SELECT customer_state AS state, COUNT(*) AS n_customers
    FROM olist_customers
    GROUP BY customer_state
), seller_states AS (
    SELECT seller_state AS state, COUNT(*) AS n_sellers
    FROM olist_sellers
    GROUP BY seller_state
)
SELECT COALESCE(c.state, s.state) AS state, c.n_customers, s.n_sellers,
       CASE
           WHEN c.state IS NOT NULL AND s.state IS NOT NULL THEN 'both'
           WHEN c.state IS NOT NULL THEN 'customers_only'
           ELSE 'sellers_only'
       END AS state_presence
FROM customer_states AS c
FULL OUTER JOIN seller_states AS s ON s.state = c.state
ORDER BY state_presence DESC, state
""")
block("4.4. SELF JOIN", "Які пари продавців з одного штату, але з різних міст, можуть бути кандидатами для регіонального порівняння — і скільки таких пар у кожному штаті?", """
SELECT s1.seller_state,
       COUNT(*) AS n_pairs_other_city,
       MIN(s1.seller_id || ' / ' || s2.seller_id) AS example_pair
FROM olist_sellers AS s1
JOIN olist_sellers AS s2
  ON s1.seller_state = s2.seller_state
 AND s1.seller_id < s2.seller_id
 AND s1.seller_city IS DISTINCT FROM s2.seller_city
GROUP BY s1.seller_state
ORDER BY n_pairs_other_city DESC
LIMIT 10
""")
block("4.5. Anti-join (LEFT JOIN ... IS NULL)", "Які замовлення не мають жодного review-запису і в яких вони статусах?", """
SELECT o.order_status,
       COUNT(*) AS orders_without_review,
       MIN(o.order_purchase_timestamp) AS first_purchase,
       MAX(o.order_purchase_timestamp) AS last_purchase
FROM olist_orders AS o
LEFT JOIN olist_order_reviews AS rv ON rv.order_id = o.order_id
WHERE rv.review_row_id IS NULL
GROUP BY o.order_status
ORDER BY orders_without_review DESC
""")
block("4.6. Anti-join (NOT EXISTS)", "Скільки товарів у каталозі жодного разу не продавалися?", """
SELECT COUNT(*) AS never_sold_products,
       (SELECT COUNT(*) FROM olist_products) AS all_products
FROM olist_products AS p
WHERE NOT EXISTS (
    SELECT 1 FROM olist_order_items AS oi WHERE oi.product_id = p.product_id
)
""")

# ------------------------------------------------------------------ 5
md("## Завдання 5. GROUP BY, HAVING і агрегати")
block("5.1. Revenue per category (WHERE + HAVING)", "Які категорії мають понад 100 000 BRL gross revenue у доставлених замовленнях?", """
SELECT p.product_category_name,
       COUNT(DISTINCT oi.order_id) AS n_orders,
       SUM(oi.price)::NUMERIC(12, 2) AS gross_revenue,
       SUM(oi.freight_value)::NUMERIC(12, 2) AS freight,
       AVG(oi.price)::NUMERIC(8, 2) AS avg_item_price
FROM olist_order_items AS oi
JOIN olist_products AS p ON p.product_id = oi.product_id
JOIN olist_orders   AS o ON o.order_id   = oi.order_id
WHERE o.order_status = 'delivered'
GROUP BY p.product_category_name
HAVING SUM(oi.price) > 100000
ORDER BY gross_revenue DESC NULLS LAST
""")
md(I["where_having"])
block("5.2. AOV per customer-state (HAVING)", "Який середній чек (AOV) у штатах, де є щонайменше 100 замовлень?", """
WITH order_totals AS (
    SELECT o.order_id, c.customer_state,
           SUM(oi.price + oi.freight_value)::NUMERIC(12, 2) AS order_total
    FROM olist_orders AS o
    JOIN olist_customers AS c ON c.customer_id = o.customer_id
    JOIN olist_order_items AS oi ON oi.order_id = o.order_id
    GROUP BY o.order_id, c.customer_state
)
SELECT customer_state,
       COUNT(*) AS n_orders,
       SUM(order_total)::NUMERIC(12, 2) AS gmv,
       (SUM(order_total) / NULLIF(COUNT(*), 0))::NUMERIC(8, 2) AS aov
FROM order_totals
GROUP BY customer_state
HAVING COUNT(*) >= 100
ORDER BY aov DESC NULLS LAST
""")
block("5.3. STRING_AGG (HAVING)", "Які категорії купували повторні покупці (≥ 2 замовлення) з найбільшими витратами?", """
SELECT c.customer_unique_id,
       COUNT(DISTINCT o.order_id) AS n_orders,
       SUM(oi.price)::NUMERIC(12, 2) AS total_spend,
       STRING_AGG(DISTINCT COALESCE(p.product_category_name, '(unknown)'), ', '
                  ORDER BY COALESCE(p.product_category_name, '(unknown)')) AS categories
FROM olist_customers AS c
JOIN olist_orders AS o ON o.customer_id = c.customer_id
JOIN olist_order_items AS oi ON oi.order_id = o.order_id
LEFT JOIN olist_products AS p ON p.product_id = oi.product_id
GROUP BY c.customer_unique_id
HAVING COUNT(DISTINCT o.order_id) >= 2
ORDER BY total_spend DESC NULLS LAST
LIMIT 15
""")

# ------------------------------------------------------------------ 6
md("## Завдання 6. Set operations, window function і Reflection")
block("6.1. UNION", "Скільки унікальних штатів представлено серед клієнтів або продавців?", """
SELECT COUNT(*) AS n_states_any_role
FROM (
    SELECT customer_state AS state FROM olist_customers
    UNION
    SELECT seller_state FROM olist_sellers
) AS all_states
""")
block("6.2. INTERSECT / EXCEPT", "У яких штатах є і клієнти, і продавці, а в яких — лише клієнти?", """
SELECT state, 'both' AS presence
FROM (
    SELECT customer_state AS state FROM olist_customers
    INTERSECT
    SELECT seller_state FROM olist_sellers
) AS both_roles
UNION ALL
SELECT state, 'customers_only'
FROM (
    SELECT customer_state AS state FROM olist_customers
    EXCEPT
    SELECT seller_state FROM olist_sellers
) AS customers_only
ORDER BY presence, state
""")
block("6.3. Window: ROW_NUMBER()", "Яке найновіше замовлення кожного реального покупця і які покупці роблять найбільше повторних замовлень?", """
WITH ranked_orders AS (
    SELECT c.customer_unique_id, o.customer_id, o.order_id, o.order_purchase_timestamp,
           ROW_NUMBER() OVER (
               PARTITION BY c.customer_unique_id
               ORDER BY o.order_purchase_timestamp DESC, o.order_id DESC
           ) AS rn,
           COUNT(*) OVER (PARTITION BY c.customer_unique_id) AS n_orders
    FROM olist_orders AS o
    JOIN olist_customers AS c ON c.customer_id = o.customer_id
)
SELECT customer_unique_id, customer_id, order_id, order_purchase_timestamp, n_orders
FROM ranked_orders
WHERE rn = 1
ORDER BY n_orders DESC, customer_unique_id
LIMIT 15
""")
md("## Reflection\n\n" + I["reflection"])

nb = nbf.v4.new_notebook(cells=cells)
nb.metadata = {"kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
               "language_info": {"name": "python"}, "colab": {"provenance": []}}
nbf.write(nb, ROOT / "notebooks/hw4_olist.ipynb")
print("wrote notebook")
