# Устройство checkpoint F1-22 R2

Модуль `source/sales_template_checkpoint.py` — транспортная форма уже выбранного шаблона. Он не выбирает локаль, не выдаёт разрешение на отправку и не заменяет F106, F120, F122 или F130.

Публичная поверхность:

- `TemplateCheckpointError` — наследник `ValueError`; `.code` и `str(error)` содержат только машинный код;
- `capture_checkpoint` — фиксирует вход в канонических байтах после одного вызова F122;
- `materialize_checkpoint` — восстанавливает и заново проверяет замороженный шаблон;
- `prepare_checkpoint_materials` — перед внешним save сравнивает checkpoint с текущим результатом F130.

Зависимости подключены модульными импортами `sales_template_materialization` и `sales_runtime_materialization`. Вызовы идут через публичные функции этих модулей, поэтому их можно наблюдать без подмены ядра.

## Каноническая форма

Payload ровно из трёх полей: `loaded_registry`, `bound_language`, `template_id`. Оболочка ровно из `schema_version` (`FIRST_TEMPLATE_CHECKPOINT_V1`), `payload` и `sha256`.

`Canonical` — `json.dumps` с `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`, затем UTF-8. Digest — lowercase SHA-256 от `Canonical(payload)`. Blob — `Canonical(envelope)` без BOM и без завершающей новой строки. Ключи словарей сортируются, списки и пробелы внутри текстов не нормализуются.

Безопасный domain — только точные `dict`, `list` и `str`. Ключи словаря — точные `str`. Подклассы, числа, `bool`, `None`, `tuple`, чужие объекты, суррогаты U+D800–U+DFFF и циклы запрещены. Общая ссылка без цикла допустима. Глубина контейнеров считается от корня payload = 1, максимум 64. Оболочка envelope в этот бюджет не входит. Готовый blob не длиннее 1 048 576 байт включительно.

## Порядок capture

1. Корни: `loaded_registry` и `bound_language` — точные `dict`, `template_id` — точная `str`. Иначе `INVALID_CHECKPOINT_INPUT`.
2. Тот же обход domain и глубины для всего payload. Ошибка на этом шаге тоже `INVALID_CHECKPOINT_INPUT`, и F122 не вызывается.
3. Ровно один вызов `sales_template_materialization.materialize_bound_template`. Его ошибка возвращается исходным объектом. Результат F122 не подменяет payload.
4. Сборка canonical envelope и проверка конечного размера. Превышение — `CHECKPOINT_TOO_LARGE`.

## Порядок materialize

1. `blob` — точные `bytes`; обе expected-версии — точные `str` по шаблону идентификатора. Иначе `INVALID_CHECKPOINT_INPUT`.
2. Длина blob. Выше лимита — `CHECKPOINT_TOO_LARGE`.
3. Строгий UTF-8 и JSON: BOM, битая кодировка, дубликаты ключей на любом уровне, NaN/Infinity, мусор после значения, запрещённый domain, цикл, суррогат или глубина — `INVALID_CHECKPOINT_JSON`. Ведущие пробелы JSON (`space`, `tab`, `CR`, `LF`) разбираются, но ломают каноничность на шаге 5.
4. Точный набор полей и типов envelope/payload, литерал схемы и 64 lowercase hex — `INVALID_CHECKPOINT_SCHEMA`.
5. Отличие blob от `Canonical(envelope)` — `NONCANONICAL_CHECKPOINT`.
6. Несовпадение digest — `CHECKPOINT_DIGEST_MISMATCH`.
7. Ровно один вызов F122 на payload. Ошибка F122 не оборачивается. Верный digest не делает испорченный текст валидным.
8. Сначала `registry_version`, затем `language_pack_version`: `CHECKPOINT_REGISTRY_MISMATCH`, `CHECKPOINT_PACK_MISMATCH`.
9. Возвращается тот же объект, который вернул F122.

## Стык сохранения

`prepare_checkpoint_materials` сам проверяет только `callable(save_materials)`. Дальше один раз вызывается `sales_runtime_materialization.prepare_bound_materials` с текущими аргументами и внутренним callback.

F130 сам идёт по цепочке F120 → F122 → `validate_materials`. Пока эта цепочка не дошла до callback, blob не читается: истёкшая привязка и отказ consumer сохраняют свой приоритет и исходное исключение.

Внутри callback checkpoint материализуется с версиями из текущего `materials`. Полный словарь сравнивается обычным равенством. При различии — `CHECKPOINT_MATERIALS_MISMATCH`, внешний callback не вызывается. При совпадении текущий `materials` передаётся внешнему callback одним позиционным аргументом ровно один раз. Возвращается тот же объект. Исключение callback проходит тем же объектом и не приводит к повтору.

Отдельного вызова F120 из этого модуля нет.

## Откат

Установка после отдельной приёмки — только этот модуль и собственные tests/docs. Принятые `sales_template_materialization.py` и остальные зависимости не перезаписываются. Откат — удалить установленный `sales_template_checkpoint.py` и добавленные tests/docs, если их SHA совпадают с принятым возвратом. Чужие файлы не удалять.

До этой приёмки модуль не подключён к рабочей системе, очереди, SQL и провайдеру.
