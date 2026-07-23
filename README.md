# gitlab-avers

Self-hosted GitLab (`git.averstech.ru`) + шпаргалка + bridge Planka ↔ GitLab.

## Сервисы

| Сервис | Порт / сеть | Назначение |
|--------|-------------|------------|
| `gitlab` | 8080→80, 2222→22 | GitLab CE |
| `docs` | 8081 | Статика «Старт в GitLab» |
| `planka-bridge` | `planka-net` | Синхронизация с [board.averstech.ru](https://board.averstech.ru) |

## Planka ↔ GitLab

### Поведение

1. Карточку переносят в **«В работе (очередь Git)»** → Issue в проекте [`avers/AVERS`](https://git.averstech.ru/avers/AVERS). Если Issue уже был и закрыт — **переоткрывается**.
2. Issue **закрывают** → карточка едет в следующую колонку **только если** ещё в очереди Git. Иначе no-op.
3. Уже лежащие в колонке карточки при старте bridge **не** трогаются (только новые переносы).

### На сервере сейчас

- Контейнер: `planka-bridge` в `/opt/gitlab`
- Проект очереди: `avers/AVERS` (id 15)
- Planka webhook: Administration → Webhooks → **GitLab bridge** → `http://planka-bridge:8080/hooks/planka` (событие `cardUpdate`)
- GitLab webhook: Issues → `http://planka-bridge:8080/hooks/gitlab`
- В GitLab включено: `allow_local_requests_from_web_hooks_and_services` (Application settings)

> В актуальной Planka `WEBHOOKS` в `.env` **не используется** — конфиг в БД / Admin UI.

### Обновление bridge

```bash
cd /opt/gitlab
# скопировать новые файлы planka-bridge/, затем:
docker compose up -d --build planka-bridge
docker compose logs -f planka-bridge
```

### Проверка

1. На Test-доске перенести карточку в «В работе (очередь Git)» → Issue в AVERS + комментарий со ссылкой.
2. Закрыть Issue → колонка «Тестирование» (или следующая на этой доске).
