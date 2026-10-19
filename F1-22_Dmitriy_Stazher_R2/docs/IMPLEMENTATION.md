# F1-22 R2: переносимый checkpoint и проверка перед сохранением

Компонент `source/sales_template_checkpoint.py` сохраняет уже выбранный шаблон в детерминированных UTF-8 bytes. Перед внешним сохранением он сопоставляет восстановленную материализацию с результатом текущей цепи F130. Сам компонент ничего не записывает: единственный разрешённый эффект — вызов переданного callback после всех проверок.

## Три точки API

`capture_checkpoint(loaded_registry, bound_language, *, template_id)` сначала проверяет безопасный JSON domain payload и глубину контейнеров. Затем ровно один раз вызывает настоящий `sales_template_materialization.materialize_bound_template`. После успешной семантической проверки строит canonical envelope и проверяет размер готовых bytes. Выбор locale, повторный binding и F130 в capture не нужны.

`materialize_checkpoint(blob, *, expected_registry_version, expected_pack_version)` проверяет входные типы и версии, размер, strict UTF-8/JSON/domain/depth, точную схему, каноничность и SHA256 в этом порядке. После этого настоящий F122 повторно проверяет frozen payload. Затем сравниваются registry pin и pack pin. Возвращается исходный результат F122, без реконструкции.

`prepare_checkpoint_materials(blob, loaded_registry, binding_config, *, now, locale, required_template_id, pinned_pack_version, save_materials)` до F130 проверяет только `callable(save_materials)`. Затем один раз вызывает настоящий `sales_runtime_materialization.prepare_bound_materials` с текущими аргументами и внутренним callback. Поэтому текущая истёкшая привязка или отказ consumer имеют приоритет перед повреждённым blob. Внутренний callback декодирует checkpoint с версиями из текущих `materials`, сравнивает полный dict и только после equality передаёт текущий `materials` внешнему callback одним positional аргументом. Результат callback возвращается тем же объектом; исключения зависимостей и callback проходят без обёртки и повторного вызова.

## Что зафиксировано в bytes

Payload имеет ровно `loaded_registry`, `bound_language`, `template_id`. Envelope имеет ровно `schema_version`, `payload`, `sha256`; literal схемы — `FIRST_TEMPLATE_CHECKPOINT_V1`. SHA256 считается от canonical payload, затем canonical envelope становится blob. Canonical JSON: `ensure_ascii=False`, `sort_keys=True`, `separators=(",", ":")`, `allow_nan=False`, далее UTF-8 без BOM и завершающего newline.

Допустимы только точные встроенные `dict`, `list`, `str`; ключи dict — точные `str`. Подклассы, циклы, surrogate, числа, bool, None, tuple и произвольные объекты запрещены. Aliasing без цикла допустим. Payload root имеет глубину 1; максимум — 64 уровня контейнеров, envelope к глубине payload не прибавляется. Размер готового blob — максимум 1048576 bytes включительно.

Сортируются только ключи dict. Subject/body, whitespace, порядок facts и active_locales сохраняются буквально. Ошибка `TemplateCheckpointError(ValueError)` раскрывает только код через `.code` и `str(error)`.

## Стыки и ответственность интегратора

Producer передаёт реально загруженный F106 registry, уже полученный результат F120 и выбранный `template_id`. Bytes записывает существующий внешний владелец хранения. Перед save интегратор передаёт доверенные текущие registry, raw binding, aware `now`, locale, required ID, текущий pack pin и существующий callback. F130 сохраняет свою цепь F120 → F122 → consumer → callback. Модуль использует публичные API через модульные импорты; accepted зависимости не меняются.

Checkpoint не замораживает время действия F105 и не устанавливает происхождение входов. Tenant/campaign/principal, актуальная policy retrieval, STOP, lease, hold и final provider gate остаются у центральной системы. Код не читает env/файлы/сеть/системное время, не делает SQL, LLM, перевод, retry или фоновые задачи. Тесты и самостоятельный packaging helper используют файловую систему только для воспроизводимой офлайн-проверки; этот код не импортируется runtime-модулем.

## Воспроизведение сдачи

Из корня репозитория, где находятся исходный ZIP и каталог пакета:

```bash
python -B F1-22_Dmitriy_Stazher_R2/source/tests/checkpoint/helper_return.py --repo .
```

Helper проверяет SHA256 исходного ZIP `c96629b1cd13ffd07890c57297e0e21d9ffa1d6f041cf367850b252dfbaa10a7`, создаёт две независимые чистые распаковки и накладывает только разрешённые изменения. В каждой запускает package до и после, baseline, candidate, discovery собственных тестов и own. Проверяются 59 protected files, все исходные файлы вне allowlist и неизменность source во время проверки. Ненулевой own count берётся из фактического discovery и логов, skips должны быть равны нулю. Исходный `MISSING_IMPLEMENTATION`, exit 3, сохраняется как ожидаемый результат до реализации.

Затем helper обновляет фактические результаты в документах, создаёт `RETURN_MANIFEST.json` с SHA256 всех файлов кроме себя и полный `artifacts/F1-22_R2_RETURN_R1.zip` с одним корнем `F1-22_Dmitriy_Stazher_R2`. Готовый ZIP дважды открывается заново: CRC, безопасные пути, точный набор файлов и manifest, protected bytes, source bytes проверенной реализации и свежая распаковка. Итоговый SHA256 ZIP и статус этих двух проверок записываются снаружи в `artifacts/F1-22_R2_RETURN_R1.validation.json`. Внешний отчёт нужен, чтобы не создавать циклический hash ZIP внутри самого ZIP. При первом отказе helper выходит с кодом 1 и отмечает невыполненное как `NOT_RUN`.

## Проверки этой ревизии

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

## Установка и откат

Установка на actual SOURCE в эту сдачу не входит. Отдельный интегратор после независимой приёмки делает свежий hash/dependency/collision preflight, backup с фактической проверкой restore и устанавливает только новый root module и согласованные собственные tests/docs. При существующем конфликтующем пути установка останавливается; accepted kernel не перезаписывается. На actual SOURCE отдельно выполняются baseline и компонентные проверки, контролируемый откат своих добавлений и повторная установка.

Откат удаляет только установленный новый модуль при совпадении его проверенного SHA, а свои tests/docs восстанавливает из backup. Чужие изменения не удаляются. Ошибка callback после возможного внешнего эффекта не означает безопасный retry: компонент передаёт её исходным объектом и ничего не сохраняет повторно. SQL/provider activation этим пакетом не разрешается и не выполняется.
