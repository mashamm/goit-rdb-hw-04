# goit-rdb-hw-04 — Olist: typed-схема, DML, JOIN, агрегати, set operations і window functions

**Автор:** Samoilenko Mariia

## Датасет

- **Назва:** Brazilian E-Commerce Public Dataset by Olist
- **Джерело:** https://www.kaggle.com/datasets/olistbr/brazilian-ecommerce (ліцензія CC BY-NC-SA 4.0)
- **Використані файли (6):** customers, orders, order_items, products, sellers, order_reviews

## Отримання даних

- **Варіант A (основний):** notebook завантажує датасет через `kagglehub.dataset_download("olistbr/brazilian-ecommerce")` — публічний датасет доступний і без облікових даних Kaggle.
- **Варіант B (резервний):** копія 6 потрібних CSV лежить у `data/olist/`; якщо KaggleHub недоступний, notebook бере файли звідти (у Colab — завантажує з цього репозиторію).

## Кількість рядків

| Таблиця | Рядків |
|---|---|
| olist_customers | 99 441 |
| olist_orders | 99 441 |
| olist_order_items | 112 650 |
| olist_products | 32 951 |
| olist_sellers | 3 095 |
| olist_order_reviews | 99 224 |

## Структура

| Шлях | Опис |
|---|---|
| `notebooks/hw4_olist.ipynb` | Notebook з outputs: typed-схема, 4+ DML з RETURNING / ON CONFLICT, customer_segments, 6 JOIN, 3 агрегати з HAVING і STRING_AGG, UNION / INTERSECT / EXCEPT, ROW_NUMBER, reflection |
| `data/olist/` | 6 CSV Olist (варіант B) |
| `tools/build_notebook.py`, `tools/interpretations.json` | Збирання notebook |

## Запуск

Відкрийте notebook у Google Colab і виконайте **Runtime → Restart session and run all**.
PostgreSQL 16 запускається всередині notebook через `pgserver`.
