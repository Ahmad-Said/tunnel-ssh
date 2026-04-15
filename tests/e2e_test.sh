#!/usr/bin/env bash
# ── tunnel-ssh End-to-End Test Suite ─────────────────────────────────────────
#
# Prerequisites:
#   - Docker (with compose plugin)
#   - tunnel CLI installed locally (`pip install -e .`)
#
# Usage:
#   ./tests/e2e_test.sh
#
# The script spins up the Docker container, runs tests against it using the
# local CLI, and tears everything down at the end.
# ─────────────────────────────────────────────────────────────────────────────

# Disable MSYS/Git-Bash automatic path conversion (Windows)
export MSYS_NO_PATHCONV=1

# ── Configuration ────────────────────────────────────────────────────────────
HOST="localhost"
PORT=9222
TOKEN="test-secret-token"
COMPOSE_FILE="docker-compose.yml"

# Counters
PASS=0
FAIL=0

# ── Helpers ──────────────────────────────────────────────────────────────────

green()  { printf "\033[32m%s\033[0m\n" "$*"; }
red()    { printf "\033[31m%s\033[0m\n" "$*"; }
yellow() { printf "\033[33m%s\033[0m\n" "$*"; }
bold()   { printf "\033[1m%s\033[0m\n" "$*"; }

assert_contains() {
    local label="$1" output="$2" expected="$3"
    if echo "$output" | grep -qF "$expected"; then
        green "  PASS: $label"
        PASS=$((PASS + 1))
    else
        red "  FAIL: $label"
        red "    expected to contain: $expected"
        red "    got: $output"
        FAIL=$((FAIL + 1))
    fi
}

assert_exit_code() {
    local label="$1" actual="$2" expected="$3"
    if [ "$actual" -eq "$expected" ]; then
        green "  PASS: $label (exit code $actual)"
        PASS=$((PASS + 1))
    else
        red "  FAIL: $label (expected exit $expected, got $actual)"
        FAIL=$((FAIL + 1))
    fi
}

# Common tunnel flags
T="--port $PORT --token $TOKEN"

# ── Lifecycle ────────────────────────────────────────────────────────────────

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

cleanup() {
    echo ""
    yellow "--- Tearing down containers ---"
    docker compose -f "$COMPOSE_FILE" down --volumes --remove-orphans 2>/dev/null || true
}
trap cleanup EXIT

echo ""
bold "======================================================"
bold "  tunnel-ssh  E2E Test Suite"
bold "======================================================"
echo ""

# ── Step 1: Start containers ────────────────────────────────────────────────
yellow "--- Starting containers ---"
docker compose -f "$COMPOSE_FILE" up -d --build 2>&1 | tail -5

yellow "--- Waiting for server to be healthy ---"
HEALTHY=0
for i in $(seq 1 30); do
    if curl -sf "http://${HOST}:${PORT}/health" > /dev/null 2>&1; then
        green "  Server is healthy (attempt $i)"
        HEALTHY=1
        break
    fi
    sleep 1
done

if [ "$HEALTHY" -eq 0 ]; then
    red "  Server failed to start within 30s"
    docker compose -f "$COMPOSE_FILE" logs 2>&1 | tail -30
    exit 1
fi

# ══════════════════════════════════════════════════════════════════════════════
#  TESTS
# ══════════════════════════════════════════════════════════════════════════════

# ── Test: Health endpoint ────────────────────────────────────────────────────
echo ""
bold "--- Test: Health endpoint ---"
HEALTH=$(curl -sf "http://${HOST}:${PORT}/health" || echo "CURL_FAILED")
assert_contains "GET /health returns ok" "$HEALTH" '"status":"ok"'

# ── Test: exec — simple echo ────────────────────────────────────────────────
echo ""
bold "--- Test: exec echo ---"
OUTPUT=$(tunnel exec "$HOST" "echo hello-e2e" $T 2>&1 || true)
assert_contains "exec echo" "$OUTPUT" "hello-e2e"

# ── Test: exec — uname ──────────────────────────────────────────────────────
echo ""
bold "--- Test: exec uname ---"
OUTPUT=$(tunnel exec "$HOST" "uname -s" $T 2>&1 || true)
assert_contains "exec uname" "$OUTPUT" "Linux"

# ── Test: exec — whoami ──────────────────────────────────────────────────────
echo ""
bold "--- Test: exec whoami ---"
OUTPUT=$(tunnel exec "$HOST" whoami $T 2>&1 || true)
assert_contains "exec whoami" "$OUTPUT" "root"

# ── Test: exec — chained commands ────────────────────────────────────────────
echo ""
bold "--- Test: exec chained commands ---"
OUTPUT=$(tunnel exec "$HOST" "echo aaa && echo bbb && echo ccc" $T 2>&1 || true)
assert_contains "chained: aaa" "$OUTPUT" "aaa"
assert_contains "chained: bbb" "$OUTPUT" "bbb"
assert_contains "chained: ccc" "$OUTPUT" "ccc"

# ── Test: exec — non-zero exit code ─────────────────────────────────────────
echo ""
bold "--- Test: exec non-zero exit code ---"
tunnel exec "$HOST" "exit 42" $T > /dev/null 2>&1
EXIT_CODE=$?
assert_exit_code "exit 42 propagated" "$EXIT_CODE" 42

# ── Test: exec — working directory ───────────────────────────────────────────
echo ""
bold "--- Test: exec cwd option ---"
OUTPUT=$(tunnel exec "$HOST" pwd $T --cwd /tmp 2>&1 || true)
assert_contains "cwd /tmp" "$OUTPUT" "/tmp"

# ── Test: ls — root directory ────────────────────────────────────────────────
echo ""
bold "--- Test: ls root directory ---"
OUTPUT=$(tunnel ls "$HOST" / $T 2>&1 || true)
assert_contains "ls / contains etc" "$OUTPUT" "etc/"
assert_contains "ls / contains usr" "$OUTPUT" "usr/"

# ── Test: ls — /app ──────────────────────────────────────────────────────────
echo ""
bold "--- Test: ls /app ---"
OUTPUT=$(tunnel ls "$HOST" /app $T 2>&1 || true)
assert_contains "ls /app has pyproject.toml" "$OUTPUT" "pyproject.toml"
assert_contains "ls /app has src/" "$OUTPUT" "src/"

# ── Test: cat — /etc/os-release ──────────────────────────────────────────────
echo ""
bold "--- Test: cat /etc/os-release ---"
OUTPUT=$(tunnel cat "$HOST" /etc/os-release $T 2>&1 || true)
assert_contains "cat os-release has Ubuntu" "$OUTPUT" "Ubuntu"

# ── Test: put + get — file round-trip ────────────────────────────────────────
echo ""
bold "--- Test: put + get round-trip ---"
# Use relative paths to avoid MSYS/Git-Bash path conversion issues on Windows
echo "e2e-payload-$$" > .e2e_upload_test.txt
EXPECTED=$(cat .e2e_upload_test.txt)

tunnel put "$HOST" .e2e_upload_test.txt /tmp $T 2>&1 || true
REMOTE_FILE="/tmp/.e2e_upload_test.txt"

mkdir -p .e2e_download
tunnel get "$HOST" "$REMOTE_FILE" .e2e_download $T 2>&1 || true
DOWNLOADED=$(cat .e2e_download/.e2e_upload_test.txt 2>/dev/null || echo "FILE_NOT_FOUND")
assert_contains "round-trip content matches" "$DOWNLOADED" "$EXPECTED"
rm -rf .e2e_upload_test.txt .e2e_download

# ── Test: rm — delete file ───────────────────────────────────────────────────
echo ""
bold "--- Test: rm delete file ---"
tunnel exec "$HOST" "echo deleteme > /tmp/to_delete.txt" $T 2>&1 || true
OUTPUT=$(tunnel rm "$HOST" /tmp/to_delete.txt $T --force 2>&1 || true)
assert_contains "rm reports deleted" "$OUTPUT" "Deleted"

# ── Test: auth — wrong token rejected ────────────────────────────────────────
echo ""
bold "--- Test: auth rejection ---"
OUTPUT=$(tunnel exec "$HOST" "echo nope" --port "$PORT" --token "wrong-token" 2>&1 || true)
assert_contains "wrong token rejected" "$OUTPUT" "Connection closed unexpectedly"

# ══════════════════════════════════════════════════════════════════════════════
#  SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
echo ""
bold "======================================================"
if [ "$FAIL" -eq 0 ]; then
    green "  All $PASS tests passed!"
else
    echo "  $PASS passed,  $FAIL failed"
fi
bold "======================================================"
echo ""

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi



