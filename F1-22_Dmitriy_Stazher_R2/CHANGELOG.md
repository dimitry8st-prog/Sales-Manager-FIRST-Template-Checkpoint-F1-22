# Изменения F1-22 R2

Добавлен transport-компонент `source/sales_template_checkpoint.py`: `TemplateCheckpointError`, `capture_checkpoint`, `materialize_checkpoint`, `prepare_checkpoint_materials`. Он фиксирует выбранные F106/F120/F122 входы в canonical UTF-8 bytes и проверяет frozen результат перед существующим callback текущего F130.

Добавлены собственные unittest в `source/tests/checkpoint/test_*.py`, общий fixture helper `helper_cases.py` и самостоятельный `helper_return.py` для двух чистых проверок исходного ZIP с разрешённым overlay. Добавлены описание API/стыков/отката, traceability и ограничения. Evidence содержит фактические команды и раздельные stdout/stderr; исходные initial logs сохранены.

Accepted зависимости, public checks, frozen inputs и protected evidence сохраняются побайтово. Новых хранилищ, SQL, I/O в runtime-модуле, полномочий, provider calls, retry или production wiring нет. Авторство старого F122 этой ревизией не устанавливается.

## Фактическая верификация

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
