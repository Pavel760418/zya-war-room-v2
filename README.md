# ZYA War Room v2

Операционный кокпит сети «Зеленое Яблоко». Пользовательский путь данных — **SQL (1С/MSSQL)**.

## Архитектура: Streamlit Cloud → 1С

```
Streamlit Community Cloud
        │  HTTP + bearer token
        ▼
Public edge  http://81.163.35.181:3000/warroom-api/   (nginx, host network)
        │
        ├─ /warroom-api/*  → 127.0.0.1:8520  warroom-sql-gateway (systemd --user)
        │                         │
        │                         ▼
        │                   MSSQL 192.168.2.10:1433 / retail  (SELECT only)
        │
        └─ /*              → 127.0.0.1:3001  Metabase (сохранён на том же :3000)
```

Почему так: `192.168.2.10` — приватный адрес, из Streamlit Cloud **физически недоступен**.
На аналитическом хосте (`analitika` / `192.168.2.95`) наружу уже был проброшен порт **3000**.
Мы подняли на нём edge: Metabase + SQL-gateway, без открытия сырого TDS 1433 в интернет.

### Автовосстановление
- `warroom-sql-gateway.service` — `Restart=always` (systemd --user, linger enabled)
- `warroom-sql-gateway-heartbeat.timer` — health каждые 2 минуты → `var/log/gateway_health_last.json`
- `warroom-edge` (docker) — `restart: unless-stopped`
- Клиент/драйвер: retry с экспоненциальной задержкой (`WARROOM_SQL_RETRIES`)

### Если пропала связь
1. `systemctl --user status warroom-sql-gateway.service`
2. `docker ps | grep warroom-edge`
3. `curl -s http://127.0.0.1:8520/health` и `curl -s http://127.0.0.1:3000/warroom-api/health`
4. Логи: `journalctl --user -u warroom-sql-gateway -n 100`
5. Heartbeat: `cat var/log/gateway_heartbeat.json`

## Streamlit

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
streamlit run streamlit_app.py
```

На LAN используется `DATABASE_URL` из `~/.config/warroom/warroom.env`.
В Cloud — gateway URL/token (`st.secrets` или встроенный private-bridge `app/core/_cloud_bridge.py`).

### Secrets (Cloud UI)

```toml
WARROOM_GATEWAY_URL = "http://81.163.35.181:3000/warroom-api"
WARROOM_GATEWAY_TOKEN = "***"   # тот же, что в ~/.config/warroom/gateway.env
```

Прямой `DATABASE_URL` на `192.168.2.10` в Cloud **не заработает** без VPN/туннеля к LAN.

## Ссылки для открытия дашборда (без логина)

**Основная (офис / Wi‑Fi Private)** — отправлять владельцу бизнеса:
`http://192.168.2.95:8080/`

- Прямой Streamlit War Room, **без Metabase**, без пароля, без токенов в URL.
- Доступ с `192.168.2.0/24`, `10.100.0.0/23` и `10.15.0.0/24` (nginx allow/deny).
- Не открывать `http://81.163.35.181:3000/` (это Metabase → форма логина).

**Смартфон** (пока порт 3000 с интернета — это Metabase на другой машине):
`https://30b10eeeacdb8b.lhr.life/`

Streamlit Cloud (необязательный TODO): https://zya-war-room-v2-ay66kuefknxypjxopuwpaj.streamlit.app/  
сейчас с Sharing=Private (логин). Чтобы вернуть Cloud без логина — App settings → Sharing → Public.


## Физический маппинг 1С

`data/catalog/StrukturaKhraneniiaBazyDannykh.xlsx` → `app/ingestion/metadata_catalog.py`

| Логическое | Физическое |
|---|---|
| РегистрНакопления.Продажи | `_AccumRg6691` |
| ТоварыНаСкладах | `_AccumRg6601` |
| Документ.СписаниеТоваров | `_Document172` |
| Документ.Инвентаризация | `_Document124` |
| Справочник.Магазины | `_Reference64` |

## Тесты

```bash
pytest -q
```
