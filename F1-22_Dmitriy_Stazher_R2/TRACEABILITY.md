# F1-22 R2: требование → код → проверка

Нормативные источники — неизменённые `CONTRACT.md`, `BOUNDARIES.md`, `RETURN.md` и `INTEGRATION.md`. Baseline подтверждает сохранность accepted поведения, а candidate и собственные тесты проверяют новый компонент. Точные фактически обнаруженные test ID и их число записываются в `evidence/test_inventory.json` после полного запуска helper.

| Требование | Код и стык | Исполняемая проверка |
| --- | --- | --- |
| EN/RU × пять видов, synthetic third locale, буквальные тексты | `capture_checkpoint`, `materialize_checkpoint`; настоящий F122 | Codec: `test_all_kinds_en_ru_and_third_locale_real_f122_exact_envelope`; Bridge: `test_real_chain_all_kinds_en_ru_third_locale_exact_abi_and_identity` |
| Детерминированная canonical форма; порядок dict не влияет, порядок списков и whitespace сохраняются | Canonical JSON и SHA256 payload | Codec: `test_dict_key_order_is_canonical_but_list_order_is_significant`, `test_literal_unicode_whitespace_fact_order_and_fresh_results` |
| Только точные dict/list/str, ключи str; циклы, surrogate и подклассы отклоняются; aliasing разрешён | Проверка transport domain до F122 в capture и после parse в decode | Codec: `test_capture_root_types_and_subclasses_precede_real_f122`, `test_capture_nested_forbidden_types_and_exact_dict_key_types`, `test_surrogates_in_values_keys_and_template_identifier_are_rejected`, `test_aliasing_without_cycle_is_allowed_and_snapshot_is_independent`, `test_direct_list_and_indirect_cycles_are_rejected_before_f122` |
| Глубина 64 от payload root=1; envelope не добавляет уровень | Проверка payload depth в capture/decode | Codec: `test_capture_depth_64_reaches_real_f122_and_65_does_not`, `test_decode_depth_uses_payload_root_without_envelope_extra_level` |
| 1048576 bytes включительно с валидным большим текстом в loaded и bound | Конечный размер capture; ранний byte limit decode | Codec: `test_large_matching_text_at_limit_minus_one_exact_and_plus_one`, `test_capture_semantic_failure_precedes_final_size_but_decode_size_precedes_json` |
| Exact bytes и версии до size/parse; strict UTF-8, BOM/duplicate keys/NaN/Infinity/trailing junk запрещены | Входной ABI, JSON parse и безопасный domain | Codec: `test_blob_exact_bytes_required_before_size_and_parse`, `test_expected_versions_exact_types_identifier_regex_and_precedence`, `test_strict_utf8_bom_syntax_and_trailing_garbage`, `test_duplicate_keys_at_envelope_payload_and_nested_template_levels`, `test_decode_numbers_booleans_null_nonfinite_and_surrogates_are_domain_errors` |
| Schema → canonical → digest → F122 → registry pin → pack pin | `materialize_checkpoint` | Codec: `test_exact_envelope_and_payload_schema_types_and_fieldsets`, `test_parse_domain_precedes_schema_and_canonical_checks`, `test_noncanonical_whitespace_key_order_and_escaping_before_digest`, `test_digest_is_sha256_of_payload_only_and_mismatch_precedes_f122_pins`, `test_pin_comparison_after_real_f122_registry_precedes_pack` |
| Реальный F122 ровно один раз в capture/decode; исходный result и exception; rehashed semantic invalidity | Модульный импорт `sales_template_materialization` и публичный API | Codec: `test_real_f122_decode_result_identity_and_exactly_one_call`, `test_real_f122_errors_preserve_identity_for_capture_and_rehashed_decode`, `test_semantic_invalidity_is_left_to_real_f122`, `test_codec_never_rebinds_or_calls_runtime_materialization` |
| До F130 проверяется только callable; blob не читается раньше текущего отказа | `prepare_checkpoint_materials` и внутренний callback | Bridge: `test_only_callable_preflight_before_f130_and_no_current_arg_revalidation`, `test_real_current_failures_precede_broken_blob_preserve_error_identity` |
| Реальная цепь F130 → F120 → F122 → consumer, затем frozen F122 | Публичный `sales_runtime_materialization.prepare_bound_materials` | Bridge: `test_real_chain_all_kinds_en_ru_third_locale_exact_abi_and_identity`, `test_dependency_sentinel_exceptions_preserved_and_no_save` |
| Полное equality текущего и frozen result: версии, locale, ID, literal text | Внутренний callback bridge | Bridge: `test_same_versions_changed_literal_subject_body_or_fact_order_mismatch`, `test_different_id_with_identical_template_text_is_mismatch`, `test_changed_current_registry_and_pack_versions_are_checkpoint_pin_errors`, `test_changed_locale_even_with_shared_pack_version_and_text_is_mismatch` |
| Zero save на отказах; один positional callback; identity return/error; без retry | Внешний `save_materials(materials)` после всех проверок | Bridge: `test_checkpoint_rejections_never_reach_external_save`, `test_callback_result_is_opaque_and_callback_exception_is_not_retried`, `test_real_chain_all_kinds_en_ru_third_locale_exact_abi_and_identity` |
| Входы/bytes не мутируются, результаты независимы, runtime без I/O | Все три публичные функции; отсутствие внешних эффектов | Codec: `test_literal_unicode_whitespace_fact_order_and_fresh_results`, `test_aliasing_without_cycle_is_allowed_and_snapshot_is_independent`; Bridge: `test_saved_materials_are_independent_between_calls_and_from_inputs`, `test_no_io_during_fresh_module_execution_or_any_public_api` |
| Сохранность accepted зависимостей и исходных входов | Неизменённый `CHECK_PACKAGE.py`, protected manifest и исходный ZIP | Helper: 59 hashes; все issued файлы вне allowlist; package до/после в двух чистых копиях |
| Полная сдача, реальные логи, exact manifest, безопасный ZIP | `source/tests/checkpoint/helper_return.py` | Две чистые проверки; повторное открытие готового ZIP два раза; внешний validation JSON |

В таблице Codec означает `test_codec.CodecTests`, Bridge — `test_bridge.BridgeCheckpointTests`; точные class names дополнительно фиксирует discovery inventory. Public checks находятся в `checks/test_checkpoint_public.py`. Собственные тесты запускаются командой `python -B RUN_CHECKS.py own` из каталога пакета. Helpers названы `helper_*.py` и не попадают в unittest pattern `test_*.py`. Harness отдельно сверяет discovery inventory с ненулевым фактическим own summary, exit 0 и skips 0.

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
