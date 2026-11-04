#!/usr/bin/env bash
# Compile the project into one executable, build/seo-page-auditor.
#
# Nuitka translates the Python code (ours, Django's and the other
# dependencies') into C, and Zig's bundled clang ("zig cc") compiles that C
# into a binary. The result runs without Python installed.
#
# Usage (inside a virtualenv):
#   pip install -r requirements-build.txt
#   scripts/build_binary.sh
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON="${PYTHON:-python}"

# Put the pinned Zig from the ziglang package first on PATH; Nuitka's --zig
# looks for "zig" there.
ZIG_DIR="$("$PYTHON" -c 'import os, ziglang; print(os.path.dirname(ziglang.__file__))')"
export PATH="$ZIG_DIR:$PATH"
# Nuitka skips --zig when CC is set, so make sure it is not.
unset CC
echo "Using zig $(zig version) from $ZIG_DIR"

# Nuitka follows normal imports by itself. Django loads a lot by name at
# runtime (apps, migrations, template tags, URL modules, templates), so those
# are listed here explicitly.
"$PYTHON" -m nuitka \
    --mode=onefile \
    --zig \
    --assume-yes-for-downloads \
    --module-parameter=django-settings-module=config.settings \
    --include-package=config \
    --include-package=audit \
    --include-package=django.contrib.admin \
    --include-package=django.contrib.auth \
    --include-package=django.contrib.contenttypes \
    --include-package=django.contrib.sessions \
    --include-package=django.contrib.messages \
    --include-package=django.contrib.staticfiles \
    --include-package=django.contrib.humanize \
    --include-package=django.templatetags \
    --include-package=django.template \
    --include-package=django.forms \
    --include-package=django.db.models \
    --include-package=django.core.serializers \
    --include-package=rest_framework \
    --nofollow-import-to='*.tests' \
    --include-package-data=django \
    --include-package-data=rest_framework \
    --include-package-data=googleapiclient:discovery_cache/documents/searchconsole.v1.json \
    --include-data-dir=audit/templates=audit/templates \
    --include-data-dir=sample_data=sample_data \
    --output-dir=build \
    --output-filename=seo-page-auditor \
    --remove-output \
    manage.py

echo "Built: build/seo-page-auditor ($(du -h build/seo-page-auditor | cut -f1))"
