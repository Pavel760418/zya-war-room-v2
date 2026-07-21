# ZYA War Room v2

Версия v2 усиливает пилот двумя отдельными управленческими блоками:
1. `drill-down карточка магазина` — детализация день / неделя / месяц, причины отклонений, локальные риски.
2. `action layer` — управленческие комментарии и рекомендуемые действия по KPI-рискам.

Также добавлен режим `demo`, который генерирует реалистичные случайные данные по сети магазинов, чтобы оценить веб-приложение в условиях боевого визуального потока.

## Запуск (FastAPI-версия)
```bash
cd zya-war-room-v2
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements-fastapi.txt   # FastAPI + общее ядро
uvicorn app.main:app --reload
```

> Для Streamlit-версии смотрите раздел «Streamlit-версия» ниже (ставится через
> `requirements.txt`). Основной способ запуска продукта — Streamlit.

## Режимы
- Excel pilot: `http://127.0.0.1:8000/`
- Demo mode: `http://127.0.0.1:8000/?mode=demo`

## Streamlit-версия

Streamlit-версия повторяет визуальный дизайн и бизнес-логику War Room, добавляет
загрузку исходного Excel через интерфейс и устойчивый ingestion с диагностикой.

### Запуск локально
```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt    # только Streamlit-зависимости
streamlit run streamlit_app.py     # откроется http://localhost:8501
```

### Возможности
- Левый сайдбар: навигация («Дашборд» / «Диагностика загрузки»), выбор источника
  данных (Excel pilot / Demo random), загрузка исходного Excel (`.xlsx`) и кнопка
  **«Скачать шаблон Excel»** (`st.download_button`).
- Excel pilot читает эталонный файл `data/war-room-template-2-no-traffic.xlsx`, либо
  загруженный пользователем файл. Demo random генерирует сеть из 24 магазинов.
- Устойчивый ingestion: распознаёт переименованные листы и колонки по алиасам,
  находит сдвинутые заголовки, приводит типы, отбрасывает мусор и **не падает** на
  битом файле — вместо этого показывает предупреждения и раздел «Диагностика загрузки».
- **Шаблон Excel** генерируется программно (`app/ingestion/template.py`) со всеми
  листами, каноническими заголовками, примерами строк и листом-инструкцией с
  пометкой обязательных полей. Скачанный шаблон полностью совместим с ingestion.

### Деплой в Streamlit Community Cloud
1. Запушить репозиторий в GitHub.
2. На share.streamlit.io выбрать репозиторий и указать **Main file: `streamlit_app.py`**.
3. Зависимости берутся из `requirements.txt` (минимальный набор без FastAPI/тестов),
   тема — из `.streamlit/config.toml`. Рекомендуемая версия Python — **3.12**
   (выбирается в Advanced settings при создании приложения).

### Файлы зависимостей
- `requirements.txt` — **только для Streamlit** (Streamlit Cloud использует его).
- `requirements-fastapi.txt` — зависимости FastAPI-версии (`app/main.py`).
- `requirements-dev.txt` — полное dev-окружение (Streamlit + FastAPI + `pytest`).

## Архитектура (reusable-слои)
- `app/ingestion/` — устойчивая загрузка Excel: `schema` (словарь листов/колонок и
  алиасов), `excel_loader` (data_loading), `data_mapping`, `data_validation`,
  `error_handling`, `pipeline` (оркестратор), `sample_inputs` (фикстуры).
- `app/services/metrics_service.py` — бизнес-метрики (общие для FastAPI и Streamlit).
- `app/streamlit_ui/` — слой отображения: `theme`, `formatting`, `render`, `charts`,
  `views`, `diagnostics`, `data_access`.
- `streamlit_app.py` — точка входа Streamlit. FastAPI-версия (`app/main.py`) сохранена.

### Тесты
```bash
pytest -q       # smoke/unit проверки устойчивости ingestion
```
