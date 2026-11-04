#!/usr/bin/env bash
# Run the compiled binary end to end in an empty folder, in mock mode:
# migrate, import, check, audit, then serve and request the main pages.
#
# The unit tests run against the source. This checks the things that only
# break in a compiled build: modules Django imports by name, and data files
# such as templates, static files and the sample data.
#
# Usage: scripts/smoke_test_binary.sh [path/to/binary]
set -euo pipefail

BIN="$(realpath "${1:-build/seo-page-auditor}")"
PORT="${PORT:-8765}"
SITE="https://shop.example.com/"
BASE="http://127.0.0.1:$PORT"

WORK="$(mktemp -d)"
SERVER_PID=""
cleanup() {
    if [ -n "$SERVER_PID" ]; then kill "$SERVER_PID" 2>/dev/null || true; fi
    rm -rf "$WORK"
}
trap cleanup EXIT
cd "$WORK"

export GSC_BACKEND=mock
export DJANGO_SUPERUSER_PASSWORD="smoke-test-password-123"

step() { echo; echo "==> $*"; }

# GET a URL and fail unless the status matches and the body contains $3.
expect() {
    local url="$1" status="$2" text="$3"
    local got
    got="$(curl -s -o body.out -w '%{http_code}' -b cookies.txt "${@:4}" "$url")"
    if [ "$got" != "$status" ]; then
        echo "FAIL $url: expected HTTP $status, got $got"; head -c 2000 body.out; exit 1
    fi
    if ! grep -q -- "$text" body.out; then
        echo "FAIL $url: response does not contain '$text'"; head -c 2000 body.out; exit 1
    fi
    echo "ok   $url ($got, contains '$text')"
}

step "Pipeline"
"$BIN" migrate -v0
"$BIN" import_gsc --site "$SITE"
"$BIN" check_pages --site "$SITE" | tail -1
"$BIN" run_audit --site "$SITE"
test -f db.sqlite3 || { echo "FAIL: db.sqlite3 was not created in the working directory"; exit 1; }
"$BIN" createsuperuser --noinput --username admin --email admin@example.com

step "Server"
"$BIN" runserver "127.0.0.1:$PORT" --noreload > server.log 2>&1 &
SERVER_PID=$!
for _ in $(seq 1 60); do
    curl -s -o /dev/null "$BASE/" && break
    sleep 0.5
done

expect "$BASE/" 200 "shop.example.com"
expect "$BASE/sites/1/report/" 200 "SEO report for https://shop.example.com/"
expect "$BASE/api/sites/1/issues/?severity=high&rule=BROKEN_PAGE" 200 '"rule":"BROKEN_PAGE"'
expect "$BASE/api/sites/1/issues/?severity=urgent" 400 "severity"
expect "$BASE/api/sites/1/issues/" 200 "Site Issue List" -H "Accept: text/html"
expect "$BASE/static/admin/css/base.css" 200 "body"
expect "$BASE/admin/login/" 200 "csrfmiddlewaretoken" -c cookies.txt

step "Admin login"
CSRF="$(grep -o 'name="csrfmiddlewaretoken" value="[^"]*"' body.out | head -1 | sed 's/.*value="//; s/"$//')"
STATUS="$(curl -s -o /dev/null -w '%{http_code}' -b cookies.txt -c cookies.txt \
    -H "Referer: $BASE/admin/login/" \
    --data-urlencode "csrfmiddlewaretoken=$CSRF" \
    --data-urlencode "username=admin" \
    --data-urlencode "password=$DJANGO_SUPERUSER_PASSWORD" \
    --data-urlencode "next=/admin/" \
    "$BASE/admin/login/")"
[ "$STATUS" = "302" ] || { echo "FAIL: admin login returned $STATUS, expected 302"; exit 1; }
echo "ok   admin login (302)"
expect "$BASE/admin/" 200 "Site administration"
expect "$BASE/admin/audit/issue/?severity__exact=high" 200 "Broken page"
expect "$BASE/admin/audit/pagecheck/" 200 "featherlite-trail-runner"

echo
echo "Smoke test passed."
