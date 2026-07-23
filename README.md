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
3. **Комментарии** синхронизируются в обе стороны (Planka ↔ GitLab) с антициклом (`<!-- bridge:from-… -->`). Служебные сообщения bridge не зеркалятся.
4. **Исполнители** с карточки Planka назначаются на Issue (сопоставление по email; опционально `PLANKA_GITLAB_USER_MAP`). Обновляется при создании Issue и при смене assignee в Planka.
5. Комментарии, написанные **до** переноса в очередь, подтягиваются в Issue при создании (backfill).
6. Метка на карточке Planka (`git:Front` и т.п.):
   - **основной путь:** на Issue в AVERS ставят метку `front` / `plugins` / `взяли` (один клик) → на карточке появляется `git:Front` / `git:Plugins` / `git:взяли`;
   - дополнительно: связанный MR из кодового репо (`avers/front`…) тоже ставит `git:Front`.
7. Карточку можно **создать сразу** в «В работе (очередь Git)» — Issue создаётся (нужен webhook `cardCreate`). Уже лежащие при старте bridge не трогаются.
8. Личные проекты Planka (раздел «Мои» / private) **не** создают Issues — `PLANKA_SKIP_PRIVATE_PROJECTS=true` по умолчанию. Новые личные проекты добавлять в конфиг не нужно. Командные (shared) синхронятся как раньше.

### На сервере сейчас

- Контейнер: `planka-bridge` в `/opt/gitlab`
- Проект очереди: `avers/AVERS` (id 15)
- Planka webhook: Administration → Webhooks → **GitLab bridge** → `http://planka-bridge:8080/hooks/planka` (события `cardUpdate`, **`cardCreate`**, `commentCreate`, membership)
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
