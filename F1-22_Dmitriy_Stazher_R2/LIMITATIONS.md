# Ограничения и статус F1-22 R2

Checkpoint — переносимая каноническая форма уже выбранного шаблона. SHA256 обнаруживает несовпадение payload и digest, но не подтверждает доверенного автора: знающий формат может изменить payload и пересчитать digest. Поэтому decode обязательно вызывает настоящий F122, а bridge использует текущую реальную цепь F130 и полное equality результатов.

Срок действия F105 проверяется по текущему переданному `now`. Snapshot не продлевает binding, не выбирает locale и не создаёт новые разрешения. Доверенные текущие registry/binding/now, tenant/campaign/principal, актуальность policy, STOP/lease/hold и final provider gate остаются обязанностью внешней системы. Полей `qa_verified`, `grant`, `SEND_READY`, `approved` компонент не добавляет.

Максимум 1048576 bytes и глубина 64 относятся только к новой transport-форме. Accepted API и их семантика не изменяются. Синтетические языковые примеры и большие тексты тестов не являются утверждёнными коммерческими материалами.

Единственный внешний эффект компонента — разрешённый callback bridge после всех проверок. Если callback сделал эффект и затем выбросил ошибку, компонент передаёт ту же ошибку и не повторяет сохранение. Интерпретация outcome, SQL/commit/UNKNOWN mapping и дальнейший retry здесь не реализуются.

Офлайн-проверка не является независимым аудитом и не означает готовность всего FIRST. Поиск trusted producer, live policy retrieval, установка на `actual SOURCE`, проверка restore/rollback установленного экземпляра, очередь, SQL, локализация QA и business activation не выполнялись (`NOT_RUN`, отдельная интеграционная работа по `INTEGRATION.md`). Внешние сервисы, ключи, установка пакетов и production доступ для этой сдачи не нужны.

## Фактическая верификация офлайн-пакета

<!-- RETURN_VERIFICATION_START -->

| Проверка | Чистая копия 1 | Чистая копия 2 |
| --- | --- | --- |
| `package_before` | PASS, exit 0, protected 59 | PASS, exit 0, protected 59 |
| `baseline` | PASS, exit 0, 152 тестов, skips 0 | PASS, exit 0, 152 тестов, skips 0 |
| `candidate` | PASS, exit 0, 13 тестов, skips 0 | PASS, exit 0, 13 тестов, skips 0 |
| `own` | PASS, exit 0, 38 тестов, skips 0 | PASS, exit 0, 38 тестов, skips 0 |
| `package_after` | PASS, exit 0, protected 59 | PASS, exit 0, protected 59 |

Собственные тесты: **38**, число взято из discovery и сверено с реальными логами обоих запусков. Список test ID: `evidence/test_inventory.json`. Команды, время, Python и exit code: `evidence/commands.json`; stdout/stderr сохранены отдельными `.log`. Исходный candidate дал ожидаемый `MISSING_IMPLEMENTATION`, exit 3; исходные доказательства сохранены в `evidence/initial_commands.json`.

Это воспроизводимая офлайн-проверка автора изменений. Независимая приёмка, установка на actual SOURCE, проверка доверенных producer/policy и business activation не выполнялись (`NOT_RUN`, вне этой сдачи).

<!-- RETURN_VERIFICATION_END -->
