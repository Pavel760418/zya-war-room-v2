# ZYA War Room v2

Операционный кокпит сети «Зеленое Яблоко». **Единственный пользовательский путь данных — MSSQL (1С).**
Excel остаётся только как внутренняя фикстура для unit-тестов ingestion/метрик.

## Streamlit (продукт)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
# Secrets: скопируйте .streamlit/secrets.toml.example → .streamlit/secrets.toml
# или экспортируйте DATABASE_URL / положите ~/.config/warroom/warroom.env
streamlit run streamlit_app.py
```

Health-check: `curl -s http://127.0.0.1:8501/_stcore/health` → `ok`.

### Физический маппинг 1С

Источник истины: `data/catalog/StrukturaKhraneniiaBazyDannykh.xlsx` (лист TDSheet).
Загрузчик: `app/ingestion/metadata_catalog.py`. SQL: `app/ingestion/sql_extract.py`.

| Логическое имя | Физическая таблица |
|---|---|
| РегистрНакопления.Продажи / ВыручкаИСебестоимостьПродаж | `_AccumRg6691` |
| ТоварыНаСкладах / ОстаткиТоваровКомпании | `_AccumRg6601` |
| Документ.БюджетПродаж (+ ТЧ) | `_Document107` / `_Document107_VT1803` |
| Документ.БюджетНакладных… (+ ТЧ) | `_Document105` / `_Document105_VT1724` |
| Документ.СписаниеТоваров (+ ТЧ) | `_Document172` / `_Document172_VT4675` |
| Документ.Инвентаризация (+ ТЧ) | `_Document124` / `_Document124_VT2532` |
| Справочник.ПодразделенияКомпании (магазины) | `_Reference64` |
| Справочник.Номенклатура | `_Reference58` |

### Production checklist (Streamlit Cloud → Settings → Secrets)

Вставьте **точный** блок (подставьте реальные host/user/password; хост 1С должен быть
доступен из Cloud — VPN/туннель/публичный endpoint):

```toml
# === War Room MSSQL (1С) — обязательные Secrets ===
DATABASE_URL = "mssql+pymssql://USER:PASSWORD@HOST:1433/DATABASE"

# Альтернатива отдельными ключами (если не используете DATABASE_URL):
# DB_HOST = "192.168.2.10"
# DB_PORT = "1433"
# DB_NAME = "retail"
# DB_USER = "readonly_warroom"
# DB_PASSWORD = "********"

# DATA_SOURCE_MODE = "mssql"
# WARROOM_SQL_TIMEOUT = "60"
```

Шаблон также лежит в `.streamlit/secrets.toml.example`.

После `git push` в `main` Cloud пересоберёт приложение автоматически.
URL: https://zya-war-room-v2-ay66kuefknxypjxopuwpaj.streamlit.app/

Без Secrets приложение показывает оформленный экран ошибки подключения
(`missing_database_url`) и **не** переключается на Excel.

### Локальный / LAN запуск

На сервере аналитики (`192.168.2.95`) используйте `EnvironmentFile` /
`~/.config/warroom/warroom.env` с `DATABASE_URL` на `192.168.2.10:1433/retail`.

Опциональный тестовый MSSQL (если прод недоступен):

```bash
docker compose -f docker-compose.mssql.yml up -d
```

### Зависимости

- `requirements.txt` — Streamlit + `pymssql` + openpyxl/plotly (Cloud и LAN).
- `requirements-server.txt` / `requirements-dev.txt` — расширенные наборы.
- Рекомендуемый Python на Cloud: **3.13**.

### Тесты

```bash
pip install -r requirements-dev.txt
pytest -q
```

Excel-фикстуры проверяют пайплайн маппинга; `tests/test_sql_path.py` —
физический каталог + mock SQL + опциональный live MSSQL.

## FastAPI (legacy)

```bash
pip install -r requirements-fastapi.txt
uvicorn app.main:app --reload
```
