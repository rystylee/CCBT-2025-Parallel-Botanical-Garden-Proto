#!/bin/bash
# ============================================================
# Argostranslate 言語パックインストール
# 翻訳ルート: ja -> en -> fr/fa/ar (英語を中継)
# ============================================================
set -e

echo "=== Argostranslate language pack installer ==="
echo ""

# Python executable (uv run or direct)
PY="${PYTHON:-/root/.local/bin/uv run python}"

$PY -c "
import argostranslate.package

print('Updating package index...')
argostranslate.package.update_package_index()
pkgs = argostranslate.package.get_available_packages()

# Installed check
installed = argostranslate.package.get_installed_packages()
installed_set = {(p.from_code, p.to_code) for p in installed}
print(f'Currently installed: {len(installed_set)} packages')
for f, t in sorted(installed_set):
    print(f'  {f} -> {t}')
print()

# Required pairs: ja->en (pivot), en->target languages
targets = [
    ('ja', 'en'),   # pivot (required)
    ('en', 'ja'),   # reverse (for input_controller)
    ('en', 'fr'),   # French
    ('en', 'fa'),   # Persian
    ('en', 'ar'),   # Arabic
]

for f, t in targets:
    if (f, t) in installed_set:
        print(f'{f} -> {t}: already installed, skipping')
        continue
    match = next((p for p in pkgs if p.from_code == f and p.to_code == t), None)
    if match:
        print(f'{f} -> {t}: installing...')
        match.install()
        print(f'{f} -> {t}: done')
    else:
        print(f'{f} -> {t}: NOT AVAILABLE (skipped)')

print()
print('=== Verification ===')
installed = argostranslate.package.get_installed_packages()
for p in sorted(installed, key=lambda x: (x.from_code, x.to_code)):
    print(f'  {p.from_code} -> {p.to_code}')
print(f'Total: {len(installed)} packages')
"

echo ""
echo "Done."
