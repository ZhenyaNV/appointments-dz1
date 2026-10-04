# Контракт API

Базовый адрес: http://localhost:8083/api. JSON, UTF-8. Авторизация — cookie `session`, HttpOnly, SameSite=Strict, срок 8 часов. Все операции кроме входа требуют сессию. Без неё — 401. Даты ISO 8601 с часовым поясом, интервалы [from_at, to_at). Ошибка: `{"detail":"описание"}`, при валидации `detail` — массив. Ответы не кешируются.

| Метод и путь | Параметры | Успех | Ошибки |
|---|---|---|---|
| POST /login | JSON username, password | 200: id, username; Set-Cookie | 401 неверные данные, 422 |
| POST /logout | Cookie | 200: ok=true; удаление cookie | 401 |
| GET /me | Cookie | 200: id, username | 401 |
| GET /services | — | 200: items: id, name, duration_minutes | 401 |
| GET /specialists | — | 200: items: id, name, service_ids | 401 |
| GET /appointments | page, size, status, specialist_id, from_at, to_at | 200: items, total, page, size | 401, 422 |
| GET /appointments/{id} | id | 200: карточка | 401, 404, 422 |
| GET /slots | service_id; specialist_id, from_at, to_at, page, size | 200: items, total, page, size | 401, 404 услуга, 422 |
| POST /appointments | JSON slot_id, service_id, client_name, start_at? | 201: карточка созданной записи | 401, 404 слот/услуга, 409 пересечение/длительность/услуга специалиста, 422 |
| POST /appointments/{id}/cancel | id | 200: карточка со status=cancelled | 401, 404, 409 уже отменена, 422 |
| GET /summary | from_at, to_at | 200: сводка | 401, 422 |

## Поля и ограничения

- `page`: 1–100000, по умолчанию 1; `size`: 1–100, по умолчанию 20. Пустая страница: items=[], total сохраняет число подходящих строк.
- `status`: active или cancelled; отсутствующий параметр включает оба статуса.
- `specialist_id`, `slot_id`, `service_id`: положительные целые. Списки с несуществующим специалистом пусты.
- `client_name`: 1–120 символов, пробелы по краям удаляются; пустое имя запрещено.
- `start_at` при создании: по умолчанию начало слота; при явном значении приём должен полностью помещаться в слот. Свободные слоты ищутся для начала приёма в начале слота.
- Период списка и сводки по умолчанию: 2026-10-01T00:00:00+03:00 — 2028-01-01T00:00:00+03:00. Выбираются записи, пересекающие период.
- Период слотов по умолчанию: 2026-10-01 — 2026-10-08, максимум 31 день; начало слота должно попадать в период.
- Слоты: id, specialist_id, specialist_name, start_at, end_at. Услуга должна поддерживаться специалистом и помещаться в слот; пересечение с активными записями исключает слот из ответа.
- Карточка и строка списка: id, slot_id, service_id, specialist_id, client_name, start_at, end_at, status, created_at, cancelled_at, specialist_name, service_name, duration_minutes, slot_start, slot_end.
- Сводка: from_at, to_at, total_appointments, cancelled, booked_minutes, available_minutes, utilization, cancellation_rate, specialists.
- Строка specialists в сводке: id, name, booked_minutes, available_minutes, total, cancelled, utilization, cancellation_rate.
- Загрузка = 100 × активные минуты / минуты расписания; интервалы обрезаются границами периода, пересекающиеся слоты расписания объединяются. Доля отмен = 100 × отменённые / все записи, пересекающие период. Пустые знаменатели дают 0.
- Отмена сохраняет историю; повторная отмена — 409. Бронирование в одной транзакции блокирует специалиста; параллельные пересекающиеся запросы не могут оба завершиться успешно.

## Пример

```json
{"slot_id":1,"service_id":1,"client_name":"Учебный клиент"}
```

Ожидается 201, если слот свободен, либо 409, если занят. Демо-учётная запись имеет доступ ко всему учебному расписанию; клиентское имя синтетическое, персональные медицинские данные не хранятся.

`GET /health` — техническая проверка БД и процесса (200: ok, project), не является операцией предметного контракта. `/docs` предоставляет автоматически построенную OpenAPI-документацию входных параметров. Полный контракт выходных полей зафиксирован здесь.

`Server-Timing`: app — серверное время до передачи тела ответа; sql — execute+fetchall вместе с клиентским декодированием; queries — число SQL-запросов. Метрики диагностики не меняют JSON-ответ.
