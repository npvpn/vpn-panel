# npvpn panel

**npvpn panel** — форк Marzban, разработанный для реальных коммерческих VPN-проектов.  
Панель оптимизирована под масштабируемые конфигурации, высокую производительность и удобное управление распределённой инфраструктурой.  
Проект развивается как основа для запуска VPN-сервисов и автоматизированных Telegram-ботов и VPN-сервисов.

---

## Назначение

- Масштабируемая архитектура для больших VPN-проектов  
- Оптимизация производительности и стабильности  
- Поддержка реальных боевых конфигураций (VLESS, XRay, multi-node)  
- Упрощённая работа с узлами и серверами  
- Интеграция с Telegram-ботами npvpn  
- Подходит для бизнеса, партнёрских сервисов и white-label решений

---



## Установка

### Обновление с оригинальной панели

Если панель была установлена из оригинального репозитория Marzban, вы можете переключить ее на `npvpn panel` без переустановки:

1. Подключитесь к серверу, где установлена панель.
2. Откройте `docker-compose`:

```bash
marzban edit
```

1. В сервисе `marzban` укажите образ `npvpn/panel:latest` и проверьте блок `volumes`:

```
services:
marzban:
    image: npvpn/panel:latest
    restart: always
    env_file: .env
    network_mode: host
    volumes:
    - /var/lib/marzban:/var/lib/marzban
    - /var/lib/marzban/logs:/var/lib/marzban-node
    - <путь к сертифиату на сервере>:<путь к сертификату внутри контейнера>
    - <путь к ключу на сервере>:<путь к ключу внутри контейнера>
    depends_on:
    mysql:
        condition: service_healthy
```

1. Загрузите новый образ:

```bash
docker pull npvpn/panel:latest
```

1. Перезапустите панель:

```bash
marzban restart
```

---



### Обычная установка

**SQLite** — без SSL, панель на порту 8000.

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install
```

Задайте аккаунт поддержки, название подписки и аккаунт бота (или оставьте пустыми). После установки:

```bash
marzban cli admin create
```

Войдите по адресу `http://<IP или домен>:8000/dashboard/#/login`.

**MySQL / MariaDB** — автоматические Let's Encrypt, volumes сертификатов в compose, HTTPS на порту 8001. UFW, админ панели и GitHub runner не ставятся (это только `install-partner`).

Перед запуском: A-запись домена на IP сервера, порт 80 свободен (certbot standalone), Debian/Ubuntu.

Интерактивно (скрипт спросит домен и email для Let's Encrypt):

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install --database mysql
```

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install --database mariadb
```

С параметрами:

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install --database mysql \
  --domain panel.example.com \
  --cert-email admin@example.com \
  --non-interactive
```

Опционально: `--uvicorn-port 8001`, `--skip-dns-check`, `--skip-cert` (сертификаты уже лежат в `/etc/letsencrypt/live/<домен>/`), `--no-logs`.

После установки создайте администратора:

```bash
marzban cli admin create
```

Войдите по адресу `https://<домен>:8001/dashboard/`.

---



### Партнёрский сервер (рекомендуется)

Полная автоматическая установка: UFW, certbot, MySQL, SSL, порт 8001, админ панели.

**Перед запуском:** создайте администратора в админке бота и скопируйте логин, MySQL-пароль и хэш пароля.  
Подробнее: [Установка панели для партнера.md](https://github.com/npvpn/Marzban-scripts/blob/master/Установка%20панели%20для%20партнера.md)

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install-partner
```

С параметрами (без интерактивных вопросов):

```bash
sudo bash -c "$(curl -sL https://github.com/npvpn/Marzban-scripts/raw/master/marzban.sh)" @ install-partner \
  --domain your-domain.tld \
  --cert-email admin@example.com \
  --mysql-password 'YOUR_MYSQL_PASSWORD' \
  --admin-username partner_admin \
  --admin-password-hash '$argon2id$...' \
  --subscription-title 'My VPN' \
  --support-telegram support_bot \
  --bot-telegram my_vpn_bot \
  --token 'GITHUB_RUNNER_REGISTRATION_TOKEN' \
  --non-interactive
```

`--token` — registration token runner’а в репе `npvpn/telegram_bot` (метка будет `partner-<bot-telegram>`). Опционально: `--project-dir /opt/marzban`, `--skip-runner`.

Панель будет доступна по адресу: `https://<домен>:8001/dashboard/`

**Обновление панели на партнёрах:** образ собирается в этом репозитории (`build.yml` → Docker Hub). Выкат — Actions приватного `[npvpn/telegram_bot](https://github.com/npvpn/telegram_bot)` (workflow **Deploy partner panels**). Инструкция: [docs/deploy.md](https://github.com/npvpn/telegram_bot/blob/master/docs/deploy.md#partner-panels).

---



## Лицензия

Проект распространяется под лицензией **AGPL-3.0**, как и оригинальный Marzban.  
Это означает, что любые модификации панели, доступные пользователям через сеть, должны быть опубликованы в открытом виде.

Отдельные интеграции (боты, биллинг, API-шлюзы), не включающие код панели, могут использовать другие лицензии.

---



## Контакты

Telegram: [https://t.me/npvpn](https://t.me/npvpn)  