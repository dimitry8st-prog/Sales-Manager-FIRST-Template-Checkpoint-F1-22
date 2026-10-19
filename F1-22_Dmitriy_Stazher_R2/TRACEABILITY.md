# Прослеживаемость F1-22 R2

Код — `source/sales_template_checkpoint.py`. Сырые журналы второго прогона на чистой копии: `evidence/clean_baseline.stdout.log`, `evidence/clean_candidate.stdout.log`, `evidence/clean_own.stdout.log`. Сводка команд и кодов выхода — `evidence/commands.json`.

| Требование | Код | Тест | Журнал |
| --- | --- | --- | --- |
| EN/RU, пять видов и synthetic third locale, точный текст | `capture_checkpoint`, `materialize_checkpoint`, `prepare_checkpoint_materials` | `test_roundtrip.RoundtripTests.test_en_ru_five_kinds_and_third_locale_keep_exact_text`; `test_bridge.BridgeTests.test_en_ru_kinds_and_synthetic_locale_roundtrip_through_f130` | `evidence/clean_own.stdout.log` |
| Unicode, пробелы и порядок фактов без нормализации | сборка payload без преобразования строк и списков | `test_literal_fixture_preserves_unicode_whitespace_and_fact_order`; `test_fact_list_order_is_not_normalized` | `evidence/clean_own.stdout.log` |
| Одинаковые байты при перестановке ключей dict | `_canonical` со `sort_keys=True` | `test_dict_key_order_does_not_change_canonical_bytes` | `evidence/clean_own.stdout.log` |
| Запрещённые типы, подклассы, циклы; допустимый alias | `_walk`, проверка точного `type` в `capture_checkpoint` | `test_forbidden_types_and_subclasses_never_call_f122`; `test_cycles_rejected_and_diamond_alias_is_not_a_cycle`; `test_shared_containers_without_cycle_roundtrip_and_stay_shared` | `evidence/clean_own.stdout.log` |
| Дубликаты ключей, UTF-8, BOM, суррогаты, лишние поля | `_pairs`, `_decode_json`, `_decoded_domain`, `_require_schema` | `test_duplicate_keys_bom_utf8_surrogate_and_trailing_junk`; `test_schema_extras_missing_and_digest_shape` | `evidence/clean_own.stdout.log` |
| Границы глубины 64/65 и размера 1048576/1048577 на валидном тексте в loaded и bound | `_walk`, проверка `len(blob)` после F122 в capture и до разбора в materialize | `test_depth_budget_includes_payload_root_and_stops_before_f122`; `test_valid_large_text_hits_the_inclusive_byte_limit` | `evidence/clean_own.stdout.log` |
| Приоритет schema / canonical / digest и остальных дефектов | порядок в `materialize_checkpoint` | `test_error_priority_when_several_defects_exist`; публичный `test_digest_and_canonical_priority` | `evidence/clean_own.stdout.log`, `evidence/clean_candidate.stdout.log` |
| Пересчитанный digest не обходит испорченную семантику | вызов F122 после проверки digest | `test_rehashed_semantic_damage_still_calls_f122_before_pins`; `test_rehashed_damage_inside_bridge_does_not_save` | `evidence/clean_own.stdout.log` |
| Несовпадение registry, затем pack | сравнения после F122 | `test_registry_pin_is_checked_before_pack_pin`; `test_current_version_drift_uses_pin_order_and_skips_save` | `evidence/clean_own.stdout.log` |
| Настоящий F122 при capture и decode | `sales_template_materialization.materialize_bound_template` | `test_en_ru_five_kinds_and_third_locale_keep_exact_text`; `test_f122_result_object_is_returned_unchanged`; `test_semantically_invalid_but_safe_domain_reaches_real_f122` | `evidence/clean_own.stdout.log` |
| Цепочка F130 → F120 → F122 → consumer | один вызов `sales_runtime_materialization.prepare_bound_materials` | `test_real_chain_order_identity_and_single_external_save` | `evidence/clean_own.stdout.log` |
| Истёкшая текущая привязка раньше сломанного blob | blob читается только во внутреннем callback | `test_current_failures_do_not_read_checkpoint_or_save` | `evidence/clean_own.stdout.log` |
| Тот же version, изменённый буквальный текст | полное равенство словарей после F122 | `test_same_version_text_change_and_other_id_do_not_save` | `evidence/clean_own.stdout.log` |
| Другой template_id при том же тексте | то же полное равенство, поле `template_id` входит в словарь | `test_same_version_text_change_and_other_id_do_not_save` | `evidence/clean_own.stdout.log` |
| Identity результата и исключения callback | возврат `save_materials(materials)` без обёртки | `test_real_chain_order_identity_and_single_external_save`; `test_callback_error_is_the_same_object_and_is_not_retried` | `evidence/clean_own.stdout.log` |
| Ноль внешних save при отказе; один вызов при успехе и при ошибке callback | внешний callback после сравнения; исключение не перехватывается | `test_current_failures_do_not_read_checkpoint_or_save`; `test_noncallable_save_fails_before_f130`; `test_callback_error_is_the_same_object_and_is_not_retried` | `evidence/clean_own.stdout.log` |
| Входы не меняются, запрещённого I/O нет | нет файловых и сетевых операций в модуле | `test_inputs_remain_equal_after_capture`; `test_bridge_does_not_mutate_inputs_or_touch_files`; `test_source_has_no_forbidden_operations` | `evidence/clean_own.stdout.log` |
| Ошибки содержат только код | `TemplateCheckpointError` | все `assert_code` в собственных тестах и публичный `code()` | `evidence/clean_own.stdout.log`, `evidence/clean_candidate.stdout.log` |
| Зависимости F105/F106/F120/F122/F130 не изменены | файлы не редактировались | `python -B CHECK_PACKAGE.py` → `PACKAGE_PROTECTED_PASS 59` | `evidence/clean_check_package.stdout.log` |
| Baseline принятого ядра | не входит в новый модуль | `python -B RUN_CHECKS.py baseline` | `evidence/clean_baseline.stdout.log` |

Публичные checks не изменялись. Собственные тесты дополняют их наблюдениями вызовов, границами и приоритетом ошибок. Зелёный прогон не заменяет приёмку заказчиком: см. `LIMITATIONS.md`.
