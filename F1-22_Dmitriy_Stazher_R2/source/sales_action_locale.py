# -*- coding: utf-8 -*-
"""Чистое привязывание языковой версии к действию (F1-20).

Стык двух принятых компонентов: F106 (загруженный реестр языков,
FIRST_LANGUAGE_REGISTRY_LOADED_V1) и F105 (конфиг кампании-привязки,
FIRST_BINDING_INPUT_V1). Функция выбирает языковой пакет запрошенной локали,
проверяет согласованность карт версий binding↔реестр, учитывает закреплённую
(pinned) версию пакета и возвращает утверждённый шаблон и его факты для
дальшей подготовки действия. Никакого I/O, сети, БД или обращений к
окружению: время в явном аргументе ``now``; входные объекты не изменяются;
результат — независимые глубокие копии. Функция не выдаёт и не расширяет
никаких прав (никаких grant/verified/approved-маркеров в выходе).

Порядок стадий (детерминирован; при нескольких нарушениях первым срабатывает
более ранний код — precedence из CONTRACT.json):

1. INVALID_INPUT — базовые типы аргументов bind_action_locale (root-типы
   входных структур, тип и осведомлённость now, формат locale, тип
   required_template_id, тип pinned_pack_version);
2. F105: validate_first_binding(binding_config, now=now) — проверка
   конфига привязки с явным временем; ошибки FirstBindingError проходят
   как есть (словарь кодов валидатора accepted-конфига F105);
3. F106: build_policy_language_fields(loaded_registry, locale=locale) —
   полная ревалидация загруженного реестра и проекция запрошенной локали;
   ошибки LanguageRegistryError проходят как есть (в том числе
   LOCALE_NOT_ACTIVE для неактивной локали — на этой стадии, до
   привязочных сверок, по error_precedence);
4. BINDING_LANGUAGE_MISMATCH — привязка ↔ реестр: запрошенная локаль в
   allowed_locales привязки; точное равенство карт
   language_pack_versions;
5. PACK_VERSION_CHANGED — pinned_pack_version задан и не совпал с
   текущей версией пакета запрошенной локали;
6. TEMPLATE_NOT_APPROVED — required_template_id отсутствует в проверенном
   пакете этой локали;
7. FACT_SCOPE_MISMATCH — факт из fact_ids шаблона отсутствует в
   утверждённом наборе фактов привязки (подмножество, без усечения).

Выход — dict ровно по FIRST_ACTION_LANGUAGE_V1 (7 ключей, статус BOUND):
schema_version, status, locale, language_pack_version, registry_version,
approved_template (полный shape шаблона F106: kind/locale/subject/body/
fact_ids), approved_fact_ids (факты шаблона — проверенное подмножество
утверждённых фактов привязки).
"""
import copy
import re
from datetime import datetime, timezone

# Принятые зависимости (read-only по ТЗ): F105-валидатор конфига привязки
# и F106-загрузчик/проектор реестра языков.
from sales_first_binding import validate_first_binding
from sales_language_registry import build_policy_language_fields

# Маркер схемы выхода и единственный статус успешной привязки (ТЗ §4).
_ACTION_SCHEMA = "FIRST_ACTION_LANGUAGE_V1"
_STATUS_BOUND = "BOUND"

# identifier и locale — те же форматы, что у принятых F105/F106
# (локальные копии: приватные имена чужих модулей не импортируются).
_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}")
_LOCALE_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*")


class ActionLocaleError(ValueError):
    """Ошибка привязки действия к языку: стабилизированный код-only.

    code: str; str(error) возвращает ровно код — без входных данных,
    локалей, шаблонов и фактов (контракт error_class_contract).
    Наследует ValueError, как принятые ошибки F105/F106.
    """

    def __init__(self, code):
        self.code = code
        super().__init__(code)

    def __str__(self):
        # В args только код: данные входов исключены из сообщения.
        return self.args[0]


def _fail(code):
    # Паттерн проекта: короткое возбуждение собственной ошибки.
    raise ActionLocaleError(code)


def _is_identifier(value):
    # identifier: полный match регламента; не-строка не идентификатор.
    return type(value) is str and bool(_IDENTIFIER_RE.fullmatch(value))


def _is_locale(value):
    # locale_id: полный match, длина 1..64; регистр сохраняется.
    return (
        type(value) is str
        and 1 <= len(value) <= 64
        and _LOCALE_RE.fullmatch(value) is not None
    )


def _require_aware(now):
    """Проверить, что now — осведомлённый datetime.

    Стадия 1 (INVALID_INPUT): наивное время без часового пояса запрещено
    ТЗ («hidden clock отсутствуют; время передаётся явно»). Поведение и
    набор исключений-доступа повторяют _datetime_as_utc принятого F105.
    """
    if not isinstance(now, datetime):
        _fail("INVALID_INPUT")
    try:
        tzinfo = now.tzinfo
        offset = now.utcoffset()
    except (AttributeError, OverflowError, TypeError, ValueError, OSError):
        _fail("INVALID_INPUT")
    if tzinfo is None or offset is None:
        _fail("INVALID_INPUT")


def bind_action_locale(loaded_registry, binding_config, *, now, locale,
                       required_template_id, pinned_pack_version):
    """Привязать действие к языковой версии; вернуть FIRST_ACTION_LANGUAGE_V1.

    Стадии 1-7 задокументированы в докстринге модуля. Входные объекты не
    изменяются; результат — независимые глубокие копии (никаких общих
    изменяемых объектов с входом). Права не выдаются: выход несёт только
    утверждения, доказуемые из F105/F106 входов (статус BOUND и выбранные
    данные), без grant/verified/approved-дополнений.
    """
    # Стадия 1 (INVALID_INPUT): ровно те root-проверки, что дают
    # осмысленный дальнейший проход; всё специфичное для конфигов/реестра
    # остаётся своим валидаторам (стадии 2-3).
    if type(loaded_registry) is not dict or type(binding_config) is not dict:
        _fail("INVALID_INPUT")
    _require_aware(now)
    if not _is_locale(locale):
        _fail("INVALID_INPUT")
    if not _is_identifier(required_template_id):
        _fail("INVALID_INPUT")
    if pinned_pack_version is not None and not _is_identifier(pinned_pack_version):
        _fail("INVALID_INPUT")

    # Стадия 2 (F105): RAW конфиг привязки с ЯВНЫМ now; augmented-выход
    # этой же функции назад в raw-валидатор не подаётся (ТЗ). Ошибки
    # FirstBindingError проходят как есть (accepted-словарь F105).
    binding = validate_first_binding(binding_config, now=now)

    # Стадия 3 (F106): полная ревалидация loaded-реестра и проекция
    # запрошенной локали; LanguageRegistryError проходит как есть
    # (включая LOCALE_NOT_ACTIVE — до привязочных сверок).
    projection = build_policy_language_fields(loaded_registry, locale=locale)

    # Стадия 4 (BINDING_LANGUAGE_MISMATCH): привязка ↔ реестр.
    # (а) запрошенная локаль обязана быть разрешена привязкой;
    # (б) карты версий binding и реестра совпадают точно (и кейсет, и
    # значения версий) — вектор «binding/registry version mismatch».
    if locale not in set(binding["allowed_locales"]):
        _fail("BINDING_LANGUAGE_MISMATCH")
    if binding["language_pack_versions"] != loaded_registry["language_pack_versions"]:
        _fail("BINDING_LANGUAGE_MISMATCH")

    # Стадия 5 (PACK_VERSION_CHANGED): закреплённая версия, если задана,
    # обязана совпасть с текущей версией пакета (в реестр-карте она равна
    # pack["version"] — проверено F106). None = «без закрепления».
    registry_versions = loaded_registry["language_pack_versions"]
    language_pack_version = registry_versions[locale]
    if (
        pinned_pack_version is not None
        and pinned_pack_version != language_pack_version
    ):
        _fail("PACK_VERSION_CHANGED")

    # Стадия 6 (TEMPLATE_NOT_APPROVED): шаблон обязан существовать в
    # проверенном пакете запрошенной локали (проекция стадии 3 уже
    # подтвердила ревалидацию всего реестра).
    pack = loaded_registry["packs_by_locale"][locale]
    templates = pack["templates"]
    if required_template_id not in templates:
        _fail("TEMPLATE_NOT_APPROVED")
    template = templates[required_template_id]

    # Стадия 7 (FACT_SCOPE_MISMATCH): каждый факт шаблона обязан входить
    # в утверждённый набор фактов привязки. Требование идёт без усечения:
    # выходной список фактов сохраняется как есть и только тогда
    # возвращается, когда он является полным подмножеством.
    approved_fact_ids = template["fact_ids"]
    binding_fact_set = set(binding["approved_fact_ids"])
    for fact_id in approved_fact_ids:
        if fact_id not in binding_fact_set:
            _fail("FACT_SCOPE_MISMATCH")

    # Выход: ровно 7 ключей; полная копия шаблона F106 (kind/locale/
    # subject/body/fact_ids) и копия её фактов — независимые от входов.
    return {
        "schema_version": _ACTION_SCHEMA,
        "status": _STATUS_BOUND,
        "locale": locale,
        "language_pack_version": language_pack_version,
        "registry_version": loaded_registry["registry_version"],
        "approved_template": copy.deepcopy(template),
        "approved_fact_ids": copy.deepcopy(approved_fact_ids),
    }