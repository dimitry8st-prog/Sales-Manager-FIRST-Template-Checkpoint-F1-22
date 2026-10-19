# -*- coding: utf-8 -*-
"""Тесты F1-20: bind_action_locale — привязка языковой версии к действию.

Покрытие — обязательные векторы приёмки ТЗ §5 плюс негативный набор по
кодам ошибок, через публичные вызовы `bind_action_locale` (реальные
вызовы; mock самой проверяемой функции не используется):

- положительные: EN и RU по золотому вектору EXAMPLES.json (собственная
  фикстура с теми же значениями), INITIAL-шаблон без фактов, третья
  фикстурная локаль de-DE без правки ядра;
- закреплённая версия: совпадение принимает, расхождение (drift) —
  PACK_VERSION_CHANGED, pinned=None использует текущую версию;
- рассинхрон привязка/реестр: расхождение карт версий и непропущенная
  локаль — BINDING_LANGUAGE_MISMATCH; неактивная локаль — F106
  LOCALE_NOT_ACTIVE, причём этот код срабатывает РАНЬШЕ привязочных
  сверок (precedence error_precedence);
- факты вне утверждённого набора привязки — FACT_SCOPE_MISMATCH;
  шаблон, отсутствующий в пакете — TEMPLATE_NOT_APPROVED;
- propagated коды F105 (FirstBindingError: augmented-вход → INVALID_SCHEMA,
  окно валидности → INVALID_VALIDITY, запрещённый режим →
  OUTBOUND_MODE_FORBIDDEN) и F106 (LanguageRegistryError: лишний ключ
  реестра → INVALID_SCHEMA, испорченные facts → INVALID_FACT_SET);
- INVALID_INPUT через публичные функции по всем аргументам (типы, наивный
  now) и его главный порядок перед кодами F105/F106;
- неизменяемость входов (успех и путь ошибки), независимость результата,
  детерминизм повторного вызова;
- ровный набор ключей выхода и отсутствие grant/verified-расширения; строки
  ошибок содержат только код (sentinel-данные не раскрываются).
"""
import copy
import json
import unittest
from datetime import datetime
from pathlib import Path

from sales_action_locale import ActionLocaleError, bind_action_locale
from sales_first_binding import FirstBindingError, validate_first_binding
from sales_language_registry import LanguageRegistryError

# Фикстуры лежат рядом (tests/fixtures/wave3/f120); путь от самого файла,
# поэтому тесты не зависят от рабочего каталога.
_FIXTURE_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "wave3" / "f120"


def _load_fixture(name):
    # Синтетический корпус из собственных фикстур allowlist.
    return json.loads((_FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _now(value):
    # Примеры времени в фикстурах — ISO со смещением; в API — aware datetime.
    return datetime.fromisoformat(value)


def _base():
    # Каждый вызов возвращает свежую копию: тесты мутируют свои версии.
    fixture = _load_fixture("f120_positive_en_ru.json")
    fixture.pop("_comment", None)
    return fixture


def _call(base, **overrides):
    # Стадия враппера: overrides подменяют поля верхнего уровня вектора.
    data = dict(base)
    data.update(overrides)
    return bind_action_locale(
        data["loaded_registry"],
        data["binding_config"],
        now=_now(data["now"]),
        locale=data["locale"],
        required_template_id=data["required_template_id"],
        pinned_pack_version=data["pinned_pack_version"],
    )


def _expect_code(test_case, callable_obj, code):
    # Единый приёмник кода: точное значение str(error) == code.
    with test_case.assertRaises((ActionLocaleError, FirstBindingError,
                                 LanguageRegistryError)) as caught:
        callable_obj()
    test_case.assertEqual(str(caught.exception), code)
    return caught.exception


class BindActionLocalePositive(unittest.TestCase):
    """Положительный вектор: EN/RU, INITIAL-шаблон, третья локаль, pinned."""

    def test_positive_ru_golden_vector(self):
        # Золотой вектор EXAMPLES.json: полное равенство ожидаемому dict.
        base = _base()
        result = _call(base)
        self.assertEqual(result, base["expected"])

    def test_positive_en_template(self):
        # EN-ветка той же фикстуры (локаль, закрепление и ожидание меняются).
        result = _call(_base(), locale="en-GB", pinned_pack_version="en-v1")
        self.assertEqual(result["status"], "BOUND")
        self.assertEqual(result["locale"], "en-GB")
        self.assertEqual(result["language_pack_version"], "en-v1")
        self.assertEqual(result["registry_version"], "registry-v1")
        self.assertEqual(result["approved_template"]["body"],
                         "Synthetic approved example.")
        self.assertEqual(result["approved_fact_ids"], ["fact-test"])

    def test_positive_initial_template_without_facts(self):
        # INITIAL-шаблон с пустым фактовым списком остаётся разрешённым.
        result = _call(_base(), locale="en-GB", required_template_id="opening",
                       pinned_pack_version="en-v1")
        self.assertEqual(result["approved_fact_ids"], [])
        self.assertEqual(result["approved_template"]["kind"], "INITIAL")

    def test_third_locale_without_core_change(self):
        # Вектор №2: de-DE добавляется только данными фикстуры, ядро то же.
        fixture = _load_fixture("f120_third_locale.json")
        fixture.pop("_comment", None)
        result = _call(fixture)
        self.assertEqual(result, fixture["expected"])

    def test_pinned_none_uses_current_version(self):
        # pinned=None: закрепление отсутствует — берём текущую версию реестра.
        result = _call(_base(), pinned_pack_version=None)
        self.assertEqual(result["language_pack_version"], "ru-v1")
        self.assertEqual(result["status"], "BOUND")

    def test_determinism_repeat_call(self):
        # Повторный вызов на тех же данных даёт равный результат.
        first = _call(_base())
        second = _call(_base())
        self.assertEqual(first, second)


class BindActionLocaleNegativeVectors(unittest.TestCase):
    """Негативные векторы приёмки §5: каждый — ожидаемый точный код."""

    def test_pinned_version_drift_rejected(self):
        # Вектор №3 + negative из EXAMPLES.json: закрепили ru-v0 против ru-v1.
        _expect_code(self, lambda: _call(_base(), pinned_pack_version="ru-v0"),
                     "PACK_VERSION_CHANGED")

    def test_binding_registry_version_map_mismatch(self):
        # Вектор №4: карта версий привязки расходится с картой реестра.
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["language_pack_versions"]["ru-RU"] = "ru-v2"
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "BINDING_LANGUAGE_MISMATCH")

    def test_locale_not_allowed_by_binding_rejected(self):
        # Локаль исключена из привязки (allowed_locales и карта согласованы,
        # чтобы дойти до сверки с реестром) — BINDING_LANGUAGE_MISMATCH.
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["allowed_locales"] = ["en-GB"]
        binding["language_pack_versions"].pop("ru-RU")
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]), locale="ru-RU",
                                                required_template_id="explain",
                                                pinned_pack_version=None),
                     "BINDING_LANGUAGE_MISMATCH")

    def test_fact_outside_binding_rejected(self):
        # Вектор №5: факт шаблона есть в реестре, но не в утверждённом
        # наборе привязки — FACT_SCOPE_MISMATCH.
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["approved_facts"] = [
            {"fact_id": "fact-other",
             "text": "Synthetic other fact.",
             "source_ref": "fixture:fact-other"}
        ]
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "FACT_SCOPE_MISMATCH")

    def test_missing_template_rejected(self):
        # Вектор №6: шаблон отсутствует в пакете запрошенной локали.
        _expect_code(self, lambda: _call(_base(), required_template_id="clarify",
                                         locale="en-GB", pinned_pack_version="en-v1"),
                     "TEMPLATE_NOT_APPROVED")


class BindActionLocaleErrorPrecedence(unittest.TestCase):
    """Precedence кодов: F105/F106/своя сверка — в порядке error_precedence."""

    def test_inactive_locale_f106_code_precedes_binding_mismatch(self):
        # Оба нарушения сразу (локаль неактивна в реестре И карта привязки
        # расходится) — первым срабатывает код F106 (LOCALE_NOT_ACTIVE).
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["allowed_locales"] = ["en-GB", "ru-RU", "de-DE"]
        binding["language_pack_versions"] = {"en-GB": "en-v1", "ru-RU": "ru-v2",
                                             "de-DE": "de-v9"}
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]), locale="de-DE",
                                                required_template_id="explain",
                                                pinned_pack_version=None),
                     "LOCALE_NOT_ACTIVE")

    def test_invalid_input_precedes_f105_and_f106(self):
        # INVALID_INPUT — самый ранний: сломаны и оба входа, и now.
        _expect_code(self,
                     lambda: bind_action_locale({"schema_version": "X"},
                                                {"schema_version": "Y"},
                                                now=datetime(2026, 10, 12, 12),
                                                locale="not valid!!",
                                                required_template_id="x",
                                                pinned_pack_version=None),
                     "INVALID_INPUT")

    def test_f105_code_precedes_binding_mismatch(self):
        # Сломанный конфиг привязки (лишний ключ) при согласованных
        # расхождении привязки и реестра — первым срабатывает F105.
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["language_pack_versions"]["ru-RU"] = "ru-v2"
        binding["unknown_extra_key"] = "unexpected"
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "INVALID_SCHEMA")

    def test_both_inputs_broken_binding_f105_checked_first(self):
        # Правило (утверждено координатором, ревизия R2): проверка binding/
        # F105 выполняется перед F106; исходные исключения F105 и их
        # стабильные .code сохраняются без преобразования в INVALID_INPUT.
        # При двух одновременных ошибках ожидается ИСХОДНАЯ ошибка F105 —
        # здесь точный тип (FirstBindingError, не LanguageRegistryError,
        # не обёртка) и точный код (INVALID_IDENTITY от F105, а не
        # INVALID_SCHEMA, которым сломан и loaded-реестр).
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["runtime_campaign_id"] = "not-a-canonical-uuid"
        loaded = copy.deepcopy(base["loaded_registry"])
        loaded["extra_key"] = 1
        with self.assertRaises((ActionLocaleError, FirstBindingError,
                                LanguageRegistryError)) as caught:
            bind_action_locale(loaded, binding, now=_now(base["now"]),
                               locale="ru-RU", required_template_id="explain",
                               pinned_pack_version=None)
        self.assertIsInstance(caught.exception, FirstBindingError)
        self.assertNotIsInstance(caught.exception, LanguageRegistryError)
        self.assertIsInstance(caught.exception, ValueError)
        self.assertEqual(caught.exception.code, "INVALID_IDENTITY")
        self.assertEqual(str(caught.exception), "INVALID_IDENTITY")

    def test_f105_augmented_output_never_passed_back(self):
        # Augmented-выход F105 подать в bind запрещено: raw-валидатор его
        # отвергает — код INVALID_SCHEMA проходит как есть.
        base = _base()
        augmented = validate_first_binding(base["binding_config"], now=_now(base["now"]))
        self.assertEqual(augmented["schema_version"], "FIRST_BINDING_V1")
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], augmented,
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "INVALID_SCHEMA")

    def test_f105_validity_window_propagated(self):
        # Нow вне окна привязки — собственный код F105 (INVALID_VALIDITY).
        base = _base()
        late_config = copy.deepcopy(base)
        late_config["now"] = "2026-10-13T09:05:00+00:00"  # после expires_at
        _expect_code(self, lambda: _call(late_config), "INVALID_VALIDITY")

    def test_f105_outbound_mode_propagated(self):
        # Иной release_mode в конфиге привязки — код F105.
        base = _base()
        binding = copy.deepcopy(base["binding_config"])
        binding["release_mode"] = "CONTROLLED"
        _expect_code(self,
                     lambda: bind_action_locale(base["loaded_registry"], binding,
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "OUTBOUND_MODE_FORBIDDEN")

    def test_f106_extra_registry_key_propagated(self):
        # Лишний ключ в загруженном реестре — F106 INVALID_SCHEMA.
        base = _base()
        loaded = copy.deepcopy(base["loaded_registry"])
        loaded["extra_field"] = 1
        _expect_code(self,
                     lambda: bind_action_locale(loaded, base["binding_config"],
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "INVALID_SCHEMA")

    def test_f106_fact_set_dup_propagated(self):
        # Дубликат в approved_fact_ids реестра — F106 INVALID_FACT_SET.
        base = _base()
        loaded = copy.deepcopy(base["loaded_registry"])
        loaded["approved_fact_ids"] = ["fact-test", "fact-test"]
        _expect_code(self,
                     lambda: bind_action_locale(loaded, base["binding_config"],
                                                now=_now(base["now"]),
                                                locale=base["locale"],
                                                required_template_id=base["required_template_id"],
                                                pinned_pack_version=base["pinned_pack_version"]),
                     "INVALID_FACT_SET")


class BindActionLocaleInvalidInput(unittest.TestCase):
    """INVALID_INPUT по каждому аргументу через публичную функцию."""

    def test_invalid_loaded_registry_type(self):
        base = _base()
        for bad in (None, [], "registry", 42):
            with self.subTest(bad=bad):
                _expect_code(self,
                             lambda: bind_action_locale(bad, base["binding_config"],
                                                        now=_now(base["now"]),
                                                        locale="ru-RU",
                                                        required_template_id="explain",
                                                        pinned_pack_version=None),
                             "INVALID_INPUT")

    def test_invalid_binding_config_type(self):
        base = _base()
        for bad in (None, [], "binding", 42):
            with self.subTest(bad=bad):
                _expect_code(self,
                             lambda: bind_action_locale(base["loaded_registry"], bad,
                                                        now=_now(base["now"]),
                                                        locale="ru-RU",
                                                        required_template_id="explain",
                                                        pinned_pack_version=None),
                             "INVALID_INPUT")

    def test_invalid_now_types_and_naive(self):
        base = _base()
        for bad in (None, "2026-10-12T12:00:00+00:00",
                    datetime(2026, 10, 12, 12), 42):
            with self.subTest(bad=type(bad).__name__):
                _expect_code(self,
                             lambda: bind_action_locale(base["loaded_registry"],
                                                        base["binding_config"],
                                                        now=bad,
                                                        locale="ru-RU",
                                                        required_template_id="explain",
                                                        pinned_pack_version=None),
                             "INVALID_INPUT")

    def test_invalid_locale_argument(self):
        base = _base()
        for bad in (None, "", "-", "ru RU", "ru-RU!",
                    "0123456789012345678901234567890123456789012345678901234567890123456789"):
            with self.subTest(bad=bad):
                _expect_code(self,
                             lambda: bind_action_locale(base["loaded_registry"],
                                                        base["binding_config"],
                                                        now=_now(base["now"]),
                                                        locale=bad,
                                                        required_template_id="explain",
                                                        pinned_pack_version=None),
                             "INVALID_INPUT")

    def test_invalid_required_template_id(self):
        base = _base()
        for bad in (None, "", "bad id", "шаблон-кириллица", 42, []):
            with self.subTest(bad=bad):
                _expect_code(self,
                             lambda: bind_action_locale(base["loaded_registry"],
                                                        base["binding_config"],
                                                        now=_now(base["now"]),
                                                        locale="ru-RU",
                                                        required_template_id=bad,
                                                        pinned_pack_version=None),
                             "INVALID_INPUT")

    def test_invalid_pinned_pack_version_type(self):
        base = _base()
        for bad in ("", "bad version", 42, [], {}):
            with self.subTest(bad=bad):
                _expect_code(self,
                             lambda: bind_action_locale(base["loaded_registry"],
                                                        base["binding_config"],
                                                        now=_now(base["now"]),
                                                        locale="ru-RU",
                                                        required_template_id="explain",
                                                        pinned_pack_version=bad),
                             "INVALID_INPUT")


class BindActionLocalePurityAndShape(unittest.TestCase):
    """Неизменяемость входов, независимость результата, shape выхода."""

    def test_source_inputs_immutable_on_success(self):
        # Вектор №7: вызов не мутирует ни один из входных объектов.
        base = _base()
        loaded_snapshot = copy.deepcopy(base["loaded_registry"])
        binding_snapshot = copy.deepcopy(base["binding_config"])
        _call(base)
        self.assertEqual(base["loaded_registry"], loaded_snapshot)
        self.assertEqual(base["binding_config"], binding_snapshot)

    def test_source_inputs_immutable_on_error_path(self):
        # Путь ошибки тоже не оставляет мутаций.
        base = _base()
        loaded_snapshot = copy.deepcopy(base["loaded_registry"])
        binding_snapshot = copy.deepcopy(base["binding_config"])
        with self.assertRaises((ActionLocaleError, FirstBindingError,
                                LanguageRegistryError)):
            _call(base, pinned_pack_version="ru-v0")
        self.assertEqual(base["loaded_registry"], loaded_snapshot)
        self.assertEqual(base["binding_config"], binding_snapshot)

    def test_output_independent_of_inputs(self):
        # Результат — глубокие копии: правки входа после вызова не меняют
        # выдачу, правки выдачи — вход.
        base = _base()
        result = _call(base)
        base["loaded_registry"]["packs_by_locale"]["ru-RU"]["templates"][
            "explain"]["body"] = "ПОСЛЕ"
        base["loaded_registry"]["approved_fact_ids"].append("fact-zzz")
        self.assertEqual(result["approved_template"]["body"],
                         "Синтетический пример для проверки.")
        self.assertEqual(result["approved_fact_ids"], ["fact-test"])
        result["approved_fact_ids"].append("fact-mutated")
        self.assertEqual(base["loaded_registry"]["packs_by_locale"]["ru-RU"][
            "templates"]["explain"]["fact_ids"], ["fact-test"])

    def test_output_exact_keys_and_no_grant_extension(self):
        # Вектор №8: ровно 7 ключей выхода, шаблон — точный shape F106,
        # никаких grant/verified/approved-маркеров не добавляется.
        result = _call(_base())
        self.assertEqual(
            set(result),
            {"schema_version", "status", "locale", "language_pack_version",
             "registry_version", "approved_template", "approved_fact_ids"})
        self.assertEqual(result["schema_version"], "FIRST_ACTION_LANGUAGE_V1")
        self.assertEqual(result["status"], "BOUND")
        self.assertEqual(
            set(result["approved_template"]),
            {"kind", "locale", "subject", "body", "fact_ids"})
        forbidden = ("verified", "grant", "approved_by", "permission",
                     "authorization")
        flattened = json.dumps(result, ensure_ascii=False)
        for marker in forbidden:
            self.assertNotIn(marker, flattened)


class BindActionLocaleErrorContract(unittest.TestCase):
    """Контракт ошибок: ValueError, str == код, данные не раскрываются."""

    def test_error_is_value_error_with_stable_code(self):
        # Своя ошибка класса ValueError со стабильным .code.
        with self.assertRaises(ValueError) as caught:
            _call(_base(), pinned_pack_version="ru-v0")
        self.assertIsInstance(caught.exception, ActionLocaleError)
        self.assertEqual(caught.exception.code, "PACK_VERSION_CHANGED")
        self.assertEqual(str(caught.exception), "PACK_VERSION_CHANGED")

    def test_error_message_contains_code_only(self):
        # Sentinel-данные во входах не появляются в сообщении об ошибке:
        # sentinelы валидны для схемы, поэтому ошибку создаём закреплением
        # чужой версии (PACK_VERSION_CHANGED); в коде/args входов нет.
        base = _base()
        sentinel = "PRIVATE-sentinel-82zq data"
        binding = copy.deepcopy(base["binding_config"])
        binding["offer"]["name"] = sentinel
        binding["owner_approval_ref"] = sentinel
        loaded = copy.deepcopy(base["loaded_registry"])
        loaded["packs_by_locale"]["ru-RU"]["templates"]["explain"]["body"] = sentinel
        with self.assertRaises(ActionLocaleError) as caught:
            bind_action_locale(loaded, binding, now=_now(base["now"]),
                               locale="ru-RU", required_template_id="explain",
                               pinned_pack_version="ru-v0")
        self.assertEqual(str(caught.exception), "PACK_VERSION_CHANGED")
        self.assertNotIn(sentinel, str(caught.exception))
        self.assertNotIn(sentinel, repr(caught.exception.args))


if __name__ == "__main__":
    unittest.main(verbosity=2)