from __future__ import annotations

import ast
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
I18N_PATH = ROOT / "i18n.py"
TRANSLATION_CALL_RE = re.compile(r"""\bt\(\s*['"]([^'"]+)['"]""")


def load_translation_maps() -> dict[str, dict[str, str]]:
    module = ast.parse(I18N_PATH.read_text())
    translations: dict[str, dict[str, str]] = {}
    named_maps: dict[str, dict[str, str]] = {}

    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == "TRANSLATIONS":
            translations.update(ast.literal_eval(node.value))
            continue

        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id.endswith("_TRANSLATIONS"):
                    named_maps[target.id] = ast.literal_eval(node.value)
                    break
                if isinstance(target, ast.Subscript):
                    if not isinstance(target.value, ast.Name) or target.value.id != "TRANSLATIONS":
                        continue
                    language = str(ast.literal_eval(target.slice))
                    if isinstance(node.value, ast.Name) and node.value.id in named_maps:
                        translations[language] = named_maps[node.value.id]
                    else:
                        translations[language] = ast.literal_eval(node.value)
                    break
            continue

        if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
            continue

        call = node.value
        if not isinstance(call.func, ast.Attribute) or call.func.attr != "update" or not call.args:
            continue

        update_payload = ast.literal_eval(call.args[0])
        receiver = call.func.value

        if isinstance(receiver, ast.Name) and receiver.id in named_maps:
            named_maps[receiver.id].update(update_payload)
            continue

        if isinstance(receiver, ast.Subscript):
            if not isinstance(receiver.value, ast.Name) or receiver.value.id != "TRANSLATIONS":
                continue
            language = str(ast.literal_eval(receiver.slice))
            translations.setdefault(language, {}).update(update_payload)

    return translations


def extract_translation_keys(path: Path) -> set[str]:
    text = path.read_text()
    return {match.group(1) for match in TRANSLATION_CALL_RE.finditer(text)}


def scan_translation_usage() -> tuple[set[str], dict[Path, set[str]]]:
    files = [ROOT / "Home.py", *sorted((ROOT / "pages").glob("*.py"))]
    all_keys: set[str] = set()
    keys_by_file: dict[Path, set[str]] = {}

    for path in files:
        keys = extract_translation_keys(path)
        all_keys.update(keys)
        keys_by_file[path] = keys

    return all_keys, keys_by_file


def main() -> int:
    language = sys.argv[1] if len(sys.argv) > 1 else "it"
    translations = load_translation_maps()
    available_languages = sorted(translations)
    if language not in translations:
        print(f"Language '{language}' not found. Available: {', '.join(available_languages)}")
        return 1

    all_keys, keys_by_file = scan_translation_usage()
    translated_keys = set(translations[language])
    missing = sorted(key for key in all_keys if key not in translated_keys)

    print(f"Language: {language}")
    print(f"Available languages: {', '.join(available_languages)}")
    print(f"Referenced keys: {len(all_keys)}")
    print(f"Translated keys: {len(translated_keys)}")
    print(f"Missing keys: {len(missing)}")
    print()

    if not missing:
        print("No missing keys.")
        return 0

    missing_by_prefix = Counter(key.split(".", 1)[0] for key in missing)
    print("Missing by prefix:")
    for prefix, count in missing_by_prefix.most_common():
        print(f"  {prefix}: {count}")
    print()

    missing_by_file: dict[Path, list[str]] = defaultdict(list)
    for path, keys in keys_by_file.items():
        for key in sorted(keys):
            if key in translated_keys:
                continue
            missing_by_file[path].append(key)

    print("Missing by file:")
    for path, keys in sorted(missing_by_file.items(), key=lambda item: (-len(item[1]), item[0].name)):
        if not keys:
            continue
        relative = path.relative_to(ROOT)
        print(f"  {relative}: {len(keys)}")
    print()

    print("Missing keys:")
    for key in missing:
        print(f"  {key}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
