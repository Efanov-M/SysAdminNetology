# Домашнее задание к занятию «SQL. Часть 2» - Ефанов Михаил Евгеньевич

## Задание 1

Одним запросом получите информацию о магазине, в котором обслуживается более 300 покупателей, и выведите в результат следующую информацию:

фамилия и имя сотрудника из этого магазина;
город нахождения магазина;
количество пользователей, закреплённых в этом магазине.

## Выполнение

```sql
SELECT
    s.last_name,
    s.first_name,
    ci.city,
    COUNT(c.customer_id) AS customer_count
FROM store AS st
JOIN staff AS s
    ON s.store_id = st.store_id
JOIN address AS a
    ON a.address_id = st.address_id
JOIN city AS ci
    ON ci.city_id = a.city_id
JOIN customer AS c
    ON c.store_id = st.store_id
GROUP BY
    st.store_id,
    s.staff_id,
    s.last_name,
    s.first_name,
    ci.city
HAVING COUNT(c.customer_id) > 300;
```

![alt text](image.png)

## Задание 2

Получите количество фильмов, продолжительность которых больше средней продолжительности всех фильмов.

## Выполнение

```sql

SELECT COUNT(*) AS film_count
FROM film
WHERE length > (
    SELECT AVG(length)
    FROM film
);
```

![alt text](image-1.png)

## Задание 3

Получите информацию, за какой месяц была получена наибольшая сумма платежей, и добавьте информацию по количеству аренд за этот месяц.

## Выполнение

```sql

SELECT
    DATE_FORMAT(p.payment_date, '%Y-%m') AS payment_month,
    SUM(p.amount) AS total_payment,
    COUNT(DISTINCT p.rental_id) AS rental_count
FROM payment AS p
GROUP BY DATE_FORMAT(p.payment_date, '%Y-%m')
ORDER BY total_payment DESC
LIMIT 1;

```

![alt text](image-2.png)
