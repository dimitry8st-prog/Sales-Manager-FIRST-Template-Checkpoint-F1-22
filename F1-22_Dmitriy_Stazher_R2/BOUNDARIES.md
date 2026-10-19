# Границы и владельцы

Разрешено изменять только source/sales_template_checkpoint.py; добавлять source/tests/checkpoint/test_*.py, source/tests/fixtures/checkpoint/*.json, docs/*.md, TRACEABILITY.md, CHANGELOG.md, LIMITATIONS.md и evidence/* (только логи/JSON отчёты). Остальные файлы неизменяемы. Код реализации не размещать в evidence/docs; собственные helper Python разрешены только source/tests/checkpoint/helper_*.py.

F106 владеет registry/packs/facts validation; F120 — locale binding; F122 R1 — точной материализацией; F130 — текущим bind→materialize→consumer validation→single callback. Их ABI/коды/порядок не меняются. SM06 владеет языковым выбором и пятью authoring packs; его работа не повторяется. F126/127, F135, B8 и SFI04–08 сохраняют текущих исполнителей и границы. Этот компонент не хранит данные, не формирует новые authority/provider/archive DTO.

Не изменять main/worker/postgres_store/config/миграции/accepted ядро. Нет I/O, файлов, сети, SQL, env, чтения системного времени, LLM, перевода, подстановок, eval/pickle/import из checkpoint, retry или фоновой задачи. Callback — единственный разрешённый эффект, ровно в bridge и после всех проверок.

Digest — контроль целостности и каноничности, не подпись и не доказательство доверенного происхождения. Знающий формат может пересчитать digest; настоящие текущие registry/binding/now поступают от интегратора и проверяются старым ядром. Идентичность tenant/campaign/principal, актуальность snapshot-policy, STOP/lease/final provider gate остаются центральными границами. Никакие qa_verified/grant/SEND_READY/approved поля не добавлять.
