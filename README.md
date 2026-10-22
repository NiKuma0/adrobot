# Adrobot — обёртка над Keitaro

FastAPI + SQLAlchemy (async) + Alembic, гексагональная архитектура, фронт — две HTML-страницы на jQuery.

1. **Создание кампании** (`/`): название, гео (`AU` или `MX,AU,RO`), оффер (автокомплит по API Keitaro),
   группа/источник/домен. Создаётся кампания с двумя потоками:
   - `Flow 1`: фильтр `country` = указанные страны → редирект на `https://google.com`;
   - `Flow 2`: всё остальное → выбранный оффер (100%).
2. **Редактор кампании** (`/campaigns/{keitaro_id}`):
   - **Fetch streams**: подтянуть потоки из Keitaro. Потоки без офферов показываются просто как поток.
     Офферы, которых больше нет в Keitaro, остаются у нас в статусе `removed` (серые).
     Локальные неопубликованные изменения при этом сбрасываются, источник правды — Keitaro;
   - **Add offer**: добавить оффер, веса пересчитываются поровну (4 оффера → по 25%);
   - **Remove** / **Bring back**: удалить оффер (0%, серый, остаётся в архиве) / вернуть;
   - **pin**: закрепить вес оффера, при следующих пересчётах он не меняется;
     остаток до 100% делится между незакреплёнными;
   - поток с неопубликованными изменениями подсвечен жёлтым;
     **Push to Keitaro** отправляет изменения, **Cancel** откатывает их
     (новые офферы удаляются, остальные возвращаются к опубликованному состоянию).

Keitaro принимает только целые доли, поэтому остаток раздаётся первым офферам: 34/33/33.

## Запуск

Нужен [uv](https://docs.astral.sh/uv/) (Python 3.12+).

```bash
cp .env.example .env          # вписать KEITARO_API_KEY
uv sync
uv run alembic upgrade head   # миграции
uv run uvicorn app.main:app --reload
```

Открыть http://localhost:8000. Swagger доступен на `/docs`.

### Настройки (`.env`)

| Переменная | Описание |
|---|---|
| `KEITARO_URL` | адрес трекера, к нему добавляется `/admin_api/v1` |
| `KEITARO_API_KEY` | API-ключ (заголовок `Api-Key`) |
| `DATABASE_URL` | по умолчанию SQLite `sqlite+aiosqlite:///./adrobot.db`; для Postgres: `postgresql+psycopg://...` (и `uv add psycopg[binary]`). Работа с БД асинхронная: `sqlite://` и `postgresql://` автоматически получают async-драйвер |
| `DEFAULT_GROUP_ID`, `DEFAULT_TRAFFIC_SOURCE_ID`, `DEFAULT_DOMAIN_ID` | значения по умолчанию для новых кампаний |

API-ключ не даёт прочитать список доменов (`GET /domains` возвращает `[]`), поэтому домен по умолчанию
задаётся в `.env`: `4622` — это `in.posdk.xyz`.

### Миграции

```bash
uv run alembic revision --autogenerate -m "описание"   # после изменения моделей в app/domain/models.py
uv run alembic upgrade head
```

### Тесты

```bash
uv run pytest                      # все тесты
uv run pytest -m "not integration" # только unit, без БД
TEST_DATABASE_URL=postgresql://... uv run pytest -m integration  # integration на другом инстансе БД
```

В сеть тесты не ходят.

- `tests/unit/` — изолированные тесты, много параметризованных таблиц (`pytest.mark.parametrize`):
  - `domain/` — правила домена на объектах в памяти: пересчёт весов, add/remove/pin, publish/cancel, sync;
  - `application/` — use cases, все порты подменены `create_autospec` (вызов с неверной сигнатурой роняет тест);
  - `adapters/` — адаптер Keitaro на `httpx.MockTransport`, маппинг ошибок в HTTP-статусы.
- `tests/integration/` — на тестовой БД (по умолчанию временный SQLite-файл, другой инстанс задаётся через
  `TEST_DATABASE_URL`). Схема создаётся миграциями Alembic, перед каждым тестом таблицы очищаются:
  - `test_repository.py` — репозиторий: строки ↔ доменные сущности, сохранение (update/insert/delete строк), порядок, unique-ограничения;
  - `test_migrations.py` — миграции дают ровно схему моделей, downgrade/upgrade проходят;
  - `test_editor_flows.py`, `test_api.py` — сценарии редактора и HTTP API (`httpx.ASGITransport` + `dependency_overrides`)
    на фейковом трекере.

## Структура

Гексагональная архитектура (ports & adapters): зависимости направлены внутрь,
домен не знает ни про FastAPI, ни про Keitaro, ни про БД. Сущности домена — модели Pydantic; таблицы — отдельные
ORM-модели в `adapters/persistence/orm.py`, с ними работает только репозиторий: он собирает сущности
через `from_orm` и записывает их обратно в `save`/`save_stream`. Загруженная сущность — отсоединённая копия:
изменения сохраняются только через репозиторий. Unit of work — это `AsyncSession` (одна на запрос),
`save*` делает flush, коммитит use case.

```
app/
  domain/                  ядро
    models.py              Campaign, Stream, StreamOffer (Pydantic, `from_orm`): правила редактора, пересчёт весов, sync
    creation.py            разбор гео, alias новой кампании
    errors.py              NotFoundError / ConflictError / InvalidInputError
  application/             use cases (async)
    ports.py               порты: Tracker, CampaignRepository
    editor.py              fetch / add / remove / bring back / pin / publish / cancel
    creator.py             создание кампании
    offers.py              каталог офферов с кешем
    directory.py           справочники для формы, список кампаний в Keitaro
  adapters/
    keitaro.py             Tracker поверх Keitaro Admin API (httpx.AsyncClient)
    persistence/           orm.py — таблицы (SQLAlchemy); repository.py — строки ↔ доменные сущности
    web/                   FastAPI: JSON API, страницы, схемы, зависимости (Annotated), маппинг ошибок в HTTP
  container.py             composition root: какие адаптеры подставить в порты
  main.py                  FastAPI-приложение (lifespan создаёт/закрывает контейнер)
  static/                  index.html, campaign.html
migrations/                Alembic (async engine)
```

У `StreamOffer` есть локальные `state`/`share` и снимок того, что опубликовано (`published_state`/`published_share`).
Поток считается неопубликованным, если они расходятся. Cancel возвращает значения из снимка.
