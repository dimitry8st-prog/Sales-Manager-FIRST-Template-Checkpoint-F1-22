"""Reproduce the offline return from two untouched issued ZIP extractions.

Run from the repository root:
  python -B F1-22_Dmitriy_Stazher_R2/source/tests/checkpoint/helper_return.py --repo .

This helper is a standalone packaging tool, never a discovered test. It uses
only the standard library. Runtime implementation remains in its root module.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import zipfile


ROOT_NAME = "F1-22_Dmitriy_Stazher_R2"
ORIGINAL_SHA256 = "c96629b1cd13ffd07890c57297e0e21d9ffa1d6f041cf367850b252dfbaa10a7"
ARCHIVE_NAME = "F1-22_R2_RETURN_R1.zip"
BEGIN = "<!-- RETURN_VERIFICATION_START -->"
END = "<!-- RETURN_VERIFICATION_END -->"
GENERATED = {"evidence/commands.json", "evidence/final_report.json",
             "evidence/test_inventory.json", "RETURN_MANIFEST.json"}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def utc():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True,
                               indent=2) + "\n", encoding="utf-8")


def allowed_change(name):
    return (name in {"source/sales_template_checkpoint.py", "RETURN_MANIFEST.json",
                     "TRACEABILITY.md", "CHANGELOG.md", "LIMITATIONS.md"}
            or re.fullmatch(r"source/tests/checkpoint/(?:test_|helper_)[^/]+\.py", name)
            or re.fullmatch(r"source/tests/fixtures/checkpoint/[^/]+\.json", name)
            or re.fullmatch(r"docs/[^/]+\.md", name)
            or re.fullmatch(r"evidence/[^/]+\.(?:json|txt|log)", name))


def files(root):
    found = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise RuntimeError("SYMLINK:" + name)
        if path.is_file():
            if any(part in {"__pycache__", ".venv", "venv", ".git"}
                   for part in path.relative_to(root).parts):
                raise RuntimeError("FORBIDDEN_DIRECTORY:" + name)
            if path.suffix in {".pyc", ".pyo"}:
                raise RuntimeError("BYTECODE:" + name)
            found[name] = path.read_bytes()
    return found


def read_archive(path):
    found = {}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
        if bad:
            raise RuntimeError("ZIP_CRC:" + bad)
        for info in archive.infolist():
            name = info.filename
            parts = PurePosixPath(name).parts
            if (not parts or parts[0] != ROOT_NAME or len(parts) < 2
                    or name.startswith("/") or "\\" in name
                    or any(part in {".", "..", ""} for part in parts)
                    or PurePosixPath(name).as_posix() != name.rstrip("/")
                    or stat.S_ISLNK(info.external_attr >> 16)):
                raise RuntimeError("ZIP_PATH:" + name)
            if info.is_dir():
                continue
            relative = PurePosixPath(*parts[1:]).as_posix()
            if relative in found:
                raise RuntimeError("ZIP_DUPLICATE:" + relative)
            found[relative] = archive.read(info)
    return found


def populate(root, content):
    for name, data in content.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)


def inspect_issued(original, current, protected):
    if len(protected) != 59:
        raise RuntimeError("PROTECTED_COUNT:" + str(len(protected)))
    for name, want in protected.items():
        if name not in current or sha(current[name]) != want:
            raise RuntimeError("PROTECTED_CHANGED:" + name)
        if name not in original or sha(original[name]) != want:
            raise RuntimeError("ORIGINAL_PROTECTED_MISMATCH:" + name)
    for name, data in original.items():
        if not allowed_change(name) and current.get(name) != data:
            raise RuntimeError("ISSUED_OUTSIDE_ALLOWLIST_CHANGED:" + name)
    for name in current:
        if name not in original and not allowed_change(name):
            raise RuntimeError("OUTSIDE_ALLOWLIST:" + name)
    if current.get("PROTECTED_MANIFEST.json") != original.get("PROTECTED_MANIFEST.json"):
        raise RuntimeError("PROTECTED_MANIFEST_CHANGED")


def generated(name):
    return name in GENERATED or bool(re.fullmatch(r"evidence/return_[^/]+\.(?:json|log)", name))


def run_command(label, argv, cwd, evidence, commands):
    started = utc()
    tick = time.perf_counter()
    child_environment = os.environ.copy()
    child_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(argv, cwd=str(cwd), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=False, env=child_environment)
    stdout_name = "return_" + label + ".stdout.log"
    stderr_name = "return_" + label + ".stderr.log"
    (evidence / stdout_name).write_bytes(result.stdout)
    (evidence / stderr_name).write_bytes(result.stderr)
    record = {"label": label, "argv": argv, "cwd": str(cwd),
              "started_utc": started, "finished_utc": utc(),
              "elapsed_seconds": round(time.perf_counter() - tick, 6),
              "exit_code": result.returncode, "expected_exit_code": 0,
              "stdout": stdout_name, "stderr": stderr_name,
              "python_version": sys.version, "python_executable": sys.executable,
              "environment_overrides": {"PYTHONDONTWRITEBYTECODE": "1"}}
    commands.append(record)
    print(label + ": exit " + str(result.returncode), flush=True)
    if result.returncode:
        raise RuntimeError("COMMAND_FAILED:" + label)
    return (result.stdout.decode("utf-8", errors="strict"),
            result.stderr.decode("utf-8", errors="strict"))


INVENTORY_CODE = """import json,pathlib,sys,unittest
root=pathlib.Path.cwd()
sys.path.insert(0,str(root/'source'))
suite=unittest.defaultTestLoader.discover(str(root/'source/tests/checkpoint'),pattern='test_*.py')
def flatten(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item.id()
ids=list(flatten(suite))
print(json.dumps({'count':suite.countTestCases(),'test_ids':ids},sort_keys=True))
"""


def check_result(mode, stdout, stderr, expected_count):
    if mode == "baseline":
        match = re.search(r"^BASELINE_RESULT count (\d+) PASS$", stdout, re.M)
        if not match or int(match.group(1)) != 152:
            raise RuntimeError("BASELINE_SUMMARY_MISMATCH")
        count = int(match.group(1))
        if re.search(r"skipped=[1-9]|^FAILED", stderr, re.M):
            raise RuntimeError("BASELINE_SKIPPED_OR_FAILED")
    else:
        pattern = (r"^RESULT " + mode
                   + r" count (\d+) failures (\d+) errors (\d+) skips (\d+)$")
        match = re.search(pattern, stdout, re.M)
        if not match:
            raise RuntimeError("RESULT_SUMMARY_MISSING:" + mode)
        count, failures, errors, skips = map(int, match.groups())
        if count != expected_count or count <= 0 or failures or errors or skips:
            raise RuntimeError("RESULT_SUMMARY_FAILED:" + mode)
    return {"status": "PASS", "count": count, "failures": 0,
            "errors": 0, "skips": 0, "exit_code": 0}


def update_docs(package, results, own_count):
    rows = ["| Проверка | Чистая копия 1 | Чистая копия 2 |",
            "| --- | --- | --- |"]
    for name in ("package_before", "baseline", "candidate", "own", "package_after"):
        values = []
        for result in results:
            item = result[name]
            count = item.get("count")
            values.append("PASS, exit 0" + (", " + str(count) + " тестов, skips 0"
                                            if count is not None else ", protected 59"))
        rows.append("| `" + name + "` | " + " | ".join(values) + " |")
    block = (BEGIN + "\n\n" + "\n".join(rows)
             + "\n\nСобственные тесты: **" + str(own_count)
             + "**, число взято из discovery и сверено с реальными логами обоих запусков. "
             + "Список test ID: `evidence/test_inventory.json`. Команды, время, Python и exit code: "
             + "`evidence/commands.json`; stdout/stderr сохранены отдельными `.log`. "
             + "Исходный candidate дал ожидаемый `MISSING_IMPLEMENTATION`, exit 3; "
             + "исходные доказательства сохранены в `evidence/initial_commands.json`.\n\n"
             + "Это воспроизводимая офлайн-проверка автора изменений. Независимая приёмка, "
             + "установка на actual SOURCE, проверка доверенных producer/policy и business activation "
             + "не выполнялись (`NOT_RUN`, вне этой сдачи).\n\n" + END)
    for name in ("docs/IMPLEMENTATION.md", "TRACEABILITY.md", "CHANGELOG.md", "LIMITATIONS.md"):
        path = package / name
        text = path.read_text(encoding="utf-8")
        if text.count(BEGIN) != 1 or text.count(END) != 1:
            raise RuntimeError("DOC_VERIFICATION_MARKERS:" + name)
        start = text.index(BEGIN)
        stop = text.index(END, start) + len(END)
        path.write_text(text[:start] + block + text[stop:], encoding="utf-8")


def build_zip(path, content):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=9) as archive:
        for name, data in sorted(content.items()):
            info = zipfile.ZipInfo(ROOT_NAME + "/" + name, (2026, 10, 12, 0, 0, 0))
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, data, compresslevel=9)


def verify_finished_zip(path, wanted, tested_source, original, protected, index):
    content = read_archive(path)  # New ZipFile open and complete CRC pass on each call.
    if set(content) != set(wanted):
        raise RuntimeError("FINISHED_ZIP_FILESET:" + str(index))
    if any(content[name] != data for name, data in wanted.items()):
        raise RuntimeError("FINISHED_ZIP_BYTES:" + str(index))
    manifest = json.loads(content["RETURN_MANIFEST.json"].decode("utf-8"))
    actual = {name: sha(data) for name, data in content.items()
              if name != "RETURN_MANIFEST.json"}
    if manifest != actual:
        raise RuntimeError("FINISHED_ZIP_MANIFEST:" + str(index))
    if {name: data for name, data in content.items() if name.startswith("source/")} != tested_source:
        raise RuntimeError("FINISHED_ZIP_TESTED_SOURCE:" + str(index))
    inspect_issued(original, content, protected)
    with tempfile.TemporaryDirectory(prefix="f122-return-reopen-") as temporary:
        extracted = Path(temporary) / ROOT_NAME
        populate(extracted, content)
        if files(extracted) != content:
            raise RuntimeError("FINISHED_ZIP_EXTRACTION:" + str(index))
    return {"validation": index, "status": "PASS", "crc": "PASS",
            "single_root_and_safe_paths": "PASS", "file_bytes": "PASS",
            "exact_manifest": "PASS", "protected_files": 59,
            "issued_outside_allowlist": "PASS", "tested_source_bytes": "PASS",
            "fresh_extraction_bytes": "PASS", "files": len(content),
            "zip_sha256": sha(path.read_bytes())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", required=True, type=Path)
    args = parser.parse_args()
    repo = args.repo.resolve()
    package = repo / ROOT_NAME
    evidence = package / "evidence"
    artifacts = repo / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    archive_path = artifacts / ARCHIVE_NAME
    external_path = artifacts / "F1-22_R2_RETURN_R1.validation.json"
    commands = []
    results = []
    external = {"status": "FAIL", "failure_status": True, "zip_sha256": None,
                "archive": str(archive_path), "validations": [], "started_utc": utc()}
    own_inventory = None
    initial_commands = None
    try:
        if archive_path.exists():
            archive_path.unlink()  # An unsuccessful rerun must not leave an old final archive.
        original_path = repo / (ROOT_NAME + ".zip")
        if sha(original_path.read_bytes()) != ORIGINAL_SHA256:
            raise RuntimeError("ORIGINAL_ZIP_SHA256_MISMATCH")
        original = read_archive(original_path)
        snapshot = files(package)
        protected = json.loads(original["PROTECTED_MANIFEST.json"].decode("utf-8"))
        inspect_issued(original, snapshot, protected)
        initial_commands = json.loads(snapshot["evidence/initial_commands.json"].decode("utf-8"))
        by_label = {item["label"]: item for item in initial_commands}
        for label, code in (("initial_python", 0), ("initial_package", 0),
                            ("initial_baseline", 0), ("initial_candidate", 3)):
            item = by_label[label]
            if item["exit_code"] != code:
                raise RuntimeError("INITIAL_EXIT_MISMATCH:" + label)
            for key in ("stdout", "stderr"):
                if "/" in item[key] or "evidence/" + item[key] not in snapshot:
                    raise RuntimeError("INITIAL_LOG_MISSING:" + label)
        if b"MISSING_IMPLEMENTATION" not in snapshot["evidence/" + by_label["initial_candidate"]["stdout"]]:
            raise RuntimeError("INITIAL_CANDIDATE_MARKER_MISSING")
        check_result("baseline", snapshot["evidence/" + by_label["initial_baseline"]["stdout"]].decode(),
                     snapshot["evidence/" + by_label["initial_baseline"]["stderr"]].decode(), 152)
        # Frozen issued evidence and all initial evidence are copied byte for byte.
        overlay = {name: data for name, data in snapshot.items()
                   if allowed_change(name) and not generated(name)}
        tested_source = None
        with tempfile.TemporaryDirectory(prefix="f122-return-clean-") as temporary:
            for index in (1, 2):
                clean = Path(temporary) / ("clean" + str(index)) / ROOT_NAME
                populate(clean, original)
                populate(clean, overlay)
                clean_bytes = files(clean)
                inspect_issued(original, clean_bytes, protected)
                source_bytes = {name: data for name, data in clean_bytes.items()
                                if name.startswith("source/")}
                if tested_source is None:
                    tested_source = source_bytes
                elif tested_source != source_bytes:
                    raise RuntimeError("CLEAN_SOURCE_MISMATCH")
                prefix = "clean" + str(index) + "_"
                result = {"clean_extraction": index}
                output, _ = run_command(prefix + "package_before",
                    [sys.executable, "-B", "CHECK_PACKAGE.py"], clean, evidence, commands)
                if output.strip() != "PACKAGE_PROTECTED_PASS 59":
                    raise RuntimeError("PACKAGE_OUTPUT_MISMATCH")
                result["package_before"] = {"status": "PASS", "protected_count": 59, "exit_code": 0}
                for mode in ("baseline", "candidate"):
                    out, err = run_command(prefix + mode,
                        [sys.executable, "-B", "RUN_CHECKS.py", mode], clean, evidence, commands)
                    result[mode] = check_result(mode, out, err, 152 if mode == "baseline" else 13)
                out, _ = run_command(prefix + "own_inventory",
                    [sys.executable, "-B", "-c", INVENTORY_CODE], clean, evidence, commands)
                inventory = json.loads(out)
                if (not inventory["test_ids"] or inventory["count"] != len(inventory["test_ids"])
                        or len(set(inventory["test_ids"])) != inventory["count"]):
                    raise RuntimeError("INVALID_OWN_INVENTORY")
                if own_inventory is None:
                    own_inventory = inventory
                elif inventory != own_inventory:
                    raise RuntimeError("OWN_INVENTORY_MISMATCH")
                out, err = run_command(prefix + "own",
                    [sys.executable, "-B", "RUN_CHECKS.py", "own"], clean, evidence, commands)
                result["own"] = check_result("own", out, err, inventory["count"])
                output, _ = run_command(prefix + "package_after",
                    [sys.executable, "-B", "CHECK_PACKAGE.py"], clean, evidence, commands)
                if output.strip() != "PACKAGE_PROTECTED_PASS 59":
                    raise RuntimeError("PACKAGE_OUTPUT_MISMATCH")
                result["package_after"] = {"status": "PASS", "protected_count": 59, "exit_code": 0}
                if files(clean) != clean_bytes:
                    raise RuntimeError("TEST_RUN_MUTATED_PACKAGE:" + str(index))
                results.append(result)
        current = files(package)
        if {name: data for name, data in current.items() if name.startswith("source/")} != tested_source:
            raise RuntimeError("SOURCE_CHANGED_DURING_VERIFICATION")
        update_docs(package, results, own_inventory["count"])
        write_json(evidence / "test_inventory.json", own_inventory)
        report = {"status": "OFFLINE_CHECKS_PASS", "failure_status": False,
                  "scope": "Author-run offline component verification; no independent acceptance or deployment",
                  "original_zip_sha256": ORIGINAL_SHA256, "protected_count": 59,
                  "clean_extractions": results, "own_test_count": own_inventory["count"],
                  "initial_candidate": {"exit_code": 3, "expected": "MISSING_IMPLEMENTATION"},
                  "initial_evidence": "initial_commands.json (original logs retained byte for byte)",
                  "archive_validation": {"status": "RECORDED_EXTERNALLY_AFTER_ARCHIVE_CLOSE",
                                         "report": "artifacts/F1-22_R2_RETURN_R1.validation.json"},
                  "independent_acceptance": "NOT_RUN", "actual_SOURCE_installation": "NOT_RUN",
                  "trusted_producer_and_live_policy_integration": "NOT_RUN", "business_activation": "NOT_RUN"}
        write_json(evidence / "final_report.json", report)
        out, _ = run_command("final_package",
            [sys.executable, "-B", "CHECK_PACKAGE.py"], package, evidence, commands)
        if out.strip() != "PACKAGE_PROTECTED_PASS 59":
            raise RuntimeError("FINAL_PACKAGE_OUTPUT_MISMATCH")
        write_json(evidence / "commands.json", {"schema_version": 1, "python_version": sys.version,
                   "initial_commands_file": "initial_commands.json", "initial_commands": initial_commands,
                   "commands": commands, "helper_argv": sys.orig_argv, "helper_cwd": str(Path.cwd())})
        final = files(package)
        inspect_issued(original, final, protected)
        # Self is deliberately excluded; every other final file is represented exactly once.
        manifest = {name: sha(data) for name, data in final.items() if name != "RETURN_MANIFEST.json"}
        write_json(package / "RETURN_MANIFEST.json", manifest)
        final = files(package)
        build_zip(archive_path, final)
        external["zip_sha256"] = sha(archive_path.read_bytes())
        for index in (1, 2):
            external["validations"].append(verify_finished_zip(
                archive_path, final, tested_source, original, protected, index))
        if any(item["zip_sha256"] != external["zip_sha256"] for item in external["validations"]):
            raise RuntimeError("ZIP_CHANGED_BETWEEN_REOPENS")
        external.update({"status": "PASS", "failure_status": False, "finished_utc": utc(),
                         "clean_extractions": 2, "reopen_validations": 2,
                         "baseline_count": 152, "candidate_count": 13,
                         "own_count": own_inventory["count"], "skips": 0})
        write_json(external_path, external)
        print("RETURN_PASS " + str(archive_path), flush=True)
        print("ZIP_SHA256 " + external["zip_sha256"], flush=True)
        return 0
    except Exception as error:
        reason = type(error).__name__ + ":" + str(error)
        external.update({"status": "FAIL", "failure_status": True,
                         "reason": reason, "finished_utc": utc()})
        if archive_path.is_file():
            external["zip_sha256"] = sha(archive_path.read_bytes())
        write_json(external_path, external)
        if evidence.is_dir():
            write_json(evidence / "commands.json", {"schema_version": 1, "python_version": sys.version,
                       "initial_commands_file": "initial_commands.json", "initial_commands": initial_commands,
                       "commands": commands, "helper_argv": sys.orig_argv, "helper_cwd": str(Path.cwd())})
            write_json(evidence / "final_report.json", {"status": "FAIL", "failure_status": True,
                       "reason": reason, "completed_clean_extractions": results,
                       "uncompleted_checks": "NOT_RUN after first failure",
                       "independent_acceptance": "NOT_RUN", "business_activation": "NOT_RUN"})
        print("RETURN_FAIL " + reason, file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
