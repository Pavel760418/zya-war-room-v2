# ZYA War Room v2

Версия v2 усиливает пилот двумя отдельными управленческими блоками:
1. `drill-down карточка магазина` — детализация день / неделя / месяц, причины отклонений, локальные риски.
2. `action layer` — управленческие комментарии и рекомендуемые действия по KPI-рискам.

Также добавлен режим `demo`, который генерирует реалистичные случайные данные по сети магазинов, чтобы оценить веб-приложение в условиях боевого визуального потока.

## Запуск
```bash
cd zya-war-room-v2
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

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
pip install -r requirements.txt
streamlit run streamlit_app.py     # откроется http://localhost:8501
```

### Возможности
- Левый сайдбар: навигация («Дашборд» / «Диагностика загрузки»), выбор источника
  данных (Excel pilot / Demo random) и загрузка исходного Excel (`.xlsx`).
- Excel pilot читает эталонный файл `data/war-room-template-2-no-traffic.xlsx`, либо
  загруженный пользователем файл. Demo random генерирует сеть из 24 магазинов.
- Устойчивый ingestion: распознаёт переименованные листы и колонки по алиасам,
  находит сдвинутые заголовки, приводит типы, отбрасывает мусор и **не падает** на
  битом файле — вместо этого показывает предупреждения и раздел «Диагностика загрузки».

### Деплой в Streamlit Community Cloud
1. Запушить репозиторий в GitHub.
2. На share.streamlit.io выбрать репозиторий и указать main-файл `streamlit_app.py`.
3. Зависимости берутся из `requirements.txt`, тема — из `.streamlit/config.toml`.

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
