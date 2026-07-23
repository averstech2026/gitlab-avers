# Контекст проекта gitlab-avers (продолжение дома)

Дата среза: **2026-07-23**. Репозиторий: локально `d:\gitlab-avers`, remote `origin` → GitHub `averstech2026/gitlab-avers` (ветка `main`).

Self-hosted стек: GitLab `git.averstech.ru`, Planka `board.averstech.ru`, сервер **`170.168.10.152`**, код/compose на сервере в **`/opt/gitlab`**.

---

## Что это

Инфра AVERS: Docker Compose (GitLab + docs-шпаргалка + **planka-bridge**). Bridge синхронизирует Planka ↔ GitLab Issues (`avers/AVERS`).

---

## Уже сделано и задеплоено на сервер (bridge)

На сервере контейнер `planka-bridge` уже обновлялся сегодня. Ключевое поведение:

| Тема | Как работает |
|------|----------------|
| Очередь | Карточка → колонка **«В работе (очередь Git)»** → Issue в `avers/AVERS` |
| Создание сразу в очереди | Обрабатывается **`cardCreate`** (не только перенос). В Planka Admin → Webhooks нужно событие **`cardCreate`** |
| Закрытие Issue | Карточка едет в следующую колонку **только** при явном close (`action=close` / смена state→closed). Обычный update Issue колонку не двигает |
| Метки (основной путь) | На Issue клик метки → Planka: `front`→`git:Front`, `plugins`→`git:Plugins`, `backend`→`git:Backend`, `взяли`→`git:взяли`; метки `git:*` проходят как есть. Служебные `from-planka` / `planka:*` не зеркалятся |
| Метки (доп.) | Связанный MR из кодового репо тоже может поставить `git:Front` |
| Legacy | Старые метки доски `pr:Front` при синке переименовываются в `git:Front` |
| Личные проекты Planka | Private («Мои») **не** создают Issues (`PLANKA_SKIP_PRIVATE_PROJECTS=true`) |
| Комменты / assignees | Двусторонние комменты + assignees Planka→GitLab (как раньше) |

Env на сервере: `planka-bridge/.env` (секреты, не в git). Добавляли `PLANKA_SKIP_PRIVATE_PROJECTS=true`.

Файлы bridge: `planka-bridge/app/{main,settings,clients,project_labels,assignees,sync_comments,store}.py`.

---

## Известные баги / наблюдения (уже правили)

1. **Ложный перенос в «Тестируется»** при привязке к front — из‑за детекта close по `state==closed` на любом update. Исправлено: только `action=close` или явный transition в `changes.state`.
2. **Метка мелькала и пропадала** — гонка label + ложный close; плюс на доске оставалась `pr:Front` от старого кода.
3. **Создание карточки сразу в очереди Git** не создавало Issue — не было `cardCreate`. Исправлено в коде; проверить webhook в Planka UI.

---

## Что проверить дома (ручной регресс)

1. Planka webhook включает: `cardUpdate`, **`cardCreate`**, `commentCreate`, membership.
2. Новая карточка **сразу** в «В работе (очередь Git)» → Issue + комментарий со ссылкой.
3. На Issue поставить метку **`front`** → на карточке **`git:Front`**, колонка не меняется.
4. Закрыть Issue → следующая колонка + комментарий «закрыт».
5. Личный private-проект Planka → в очередь Git → Issue **не** создаётся.

В AVERS заранее создать labels: `front`, `plugins`, `взяли` (если нет).

---

## Следующая крупная задача (Иван + Рома)

**GitLab Runner + обязательные тесты перед merge** (как в спулере).

Предложенный план (ещё не начат):

1. Shared runner на `170.168.10.152` (Docker executor).
2. Пилот: проект со спулером (где тесты уже есть) → `.gitlab-ci.yml`.
3. Settings → Merge requests → **Pipelines must succeed**.
4. Тиражировать на Front / остальные (Front = Delphi — отдельный runner/образ).

Нужны от Ивана/Ромы: путь к репо спулера и команда прогона тестов.

---

## Деплой bridge (когда правите код)

```bash
# с машины разработки: скопировать planka-bridge/app/* и .env.example на сервер в /opt/gitlab/
ssh root@170.168.10.152
cd /opt/gitlab
docker compose build --no-cache planka-bridge && docker compose up -d planka-bridge
docker logs --tail 50 planka-bridge
```

Сеть Docker: external `planka-net`. Compose: `docker-compose.yml` в корне репо / на сервере.

---

## Не коммитить

- `planka-bridge/.env` (секреты) — в `.gitignore`
- `.cursor/` — локальные настройки IDE
- Скрипты деплоя с паролем SSH (если появятся снова) — не оставлять в репо

SSH на сервер ранее: user `root`, хост `170.168.10.152` (пароль не хранить в файлах репозитория).

---

## Структура репо (важное)

```
gitlab-avers/
  README.md                 # краткое поведение bridge
  CONTEXT.md                # этот файл — handoff
  docker-compose.yml        # gitlab + docs + planka-bridge
  docs-site/                # шпаргалка «Старт в GitLab»
  planka-bridge/
    .env.example
    Dockerfile
    app/main.py             # webhooks Planka/GitLab
    app/project_labels.py   # git: метки (Issue labels + MR)
    app/settings.py
    app/clients.py
    …
```

---

## Состояние git на момент среза

- Ветка: `main`
- Незакоммиченное до этого коммита: правки bridge (метки `git:`, private skip, close harden, cardCreate, issue-label map) + README + CONTEXT.md
- Remote push: в GitHub `origin/main` (не путать с self-hosted `git.averstech.ru`)
