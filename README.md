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
