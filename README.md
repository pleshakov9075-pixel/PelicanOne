# PelicanOneBot

Production-ready Telegram-бот для генерации текста, изображений, видео, аудио и 3D.

## Быстрый старт

1. Скопируйте файл окружения и заполните значения:

```bash
cp .env.example .env
```

2. Запустите сервисы:

```bash
docker compose up --build -d
```

3. Примените миграции:

```bash
docker compose run --rm migrations
```

## Systemd автозапуск

```bash
sudo mkdir -p /opt/pelicanone
sudo cp -R . /opt/pelicanone
sudo cp deploy/pelicanone.service /etc/systemd/system/pelicanone.service
sudo systemctl daemon-reload
sudo systemctl enable pelicanone.service
sudo systemctl start pelicanone.service
```

## Очистка данных

Рекомендуется настроить cron на ежедневную очистку папки `/opt/pelicanone/data`:

```bash
0 3 * * * /opt/pelicanone/scripts/cleanup_data.sh /opt/pelicanone/data
```

## Админ-команды

- `/price list`
- `/price set <код> <цена>`
- `/give <telegram_id> <сумма>`
- `/ban <telegram_id>`
- `/unban <telegram_id>`
- `/jobs`
- `/broadcast`
