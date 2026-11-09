#!/usr/bin/env bash
# Verification scaffolding for finance_dash, not product code.
#
# Drives a private, disposable copy of the app: one uvicorn process serving the API and the built
# frontend (the same shape as the live service), on a free 127.0.0.1 port, with its own SQLite file,
# blank source credentials and outbound HTTP pointed at a dead proxy.
#
#   control.sh launch    <run-id>            build the frontend, start the server, wait until usable
#   control.sh doctor    <run-id>            read-only: is this instance ours and worth driving?
#   control.sh url       <run-id>            print the instance's base URL
#   control.sh proof-dir <run-id>            create and print where this run's evidence goes
#   control.sh browser   <run-id> <args...>  chrome-devtools-axi in a session private to this run
#   control.sh ref       <run-id> '<role> "<name>"'   print the current @ref of the first element that matches
#   control.sh api       <run-id> <METHOD> <path> [json-body]   curl the instance's API
#   control.sh sql       <run-id> <query>    read-only query against the instance's database
#   control.sh stop      <run-id>            stop what launch started, remove scratch state, keep proof
set -uo pipefail

die() { echo "error: $*" >&2; exit 1; }

cmd=${1:-}
run=${2:-}
[[ -n $cmd && -n $run ]] || die "usage: control.sh launch|doctor|url|proof-dir|browser|ref|api|sql|stop <run-id> [args]"
[[ $run =~ ^[A-Za-z0-9._-]+$ ]] || die "run-id may only contain letters, digits, '.', '_' and '-'"
shift 2

root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || die "not inside a git checkout"
state=${TMPDIR:-/tmp}/finance-dash-verify/$run
archive=$root/data/csv_archive/neon
browser_session=fdverify-$run
dead_proxy=http://127.0.0.1:9

# get <key>: a value launch recorded in the state file.
get() { sed -n "s/^$1=//p" "$state/instance.env" 2>/dev/null | head -n1; }

# The captain's live checkout (systemd unit finance-dash.service) must never be driven or written to:
# the Neon upload archives into <checkout>/data and the build rewrites <checkout>/frontend/dist.
refuse_live_checkout() {
  local live real
  real=$(realpath "$root")
  for live in "$HOME/Projects/finance_dash" \
    "$(systemctl --user show finance-dash.service -p WorkingDirectory --value 2>/dev/null)"; do
    [[ -n $live && -d $live && $(realpath "$live") == "$real" ]] &&
      die "$root is the live checkout behind finance-dash.service; run from a task worktree"
  done
  return 0
}

free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

proof_dir() {
  local dir=${FD_PROOF_DIR:-$root/data/verify-proof/$run}
  mkdir -p "$dir" && echo "$dir"
}

launch() {
  refuse_live_checkout
  [[ -e $state/instance.env ]] && die "run $run already has state in $state; run 'control.sh stop $run' first"
  [[ -x $root/.venv/bin/python ]] ||
    die "no $root/.venv; create it: python3 -m venv $root/.venv && $root/.venv/bin/pip install -r $root/requirements.txt"
  [[ -d $root/frontend/node_modules ]] || die "no frontend/node_modules; run: npm --prefix $root/frontend ci"

  local port=${FD_VERIFY_PORT:-$(free_port)}
  case $port in 8000 | 8001 | 5173) die "port $port belongs to the dev or live app; pick another" ;; esac
  ss -ltn "sport = :$port" | grep -q LISTEN && die "port $port is already in use"

  mkdir -p "$state" || die "cannot create $state"
  # Neon CSVs already archived in this checkout stay; stop removes only the ones this run adds.
  if [[ -d $archive ]]; then ls -1 "$archive" > "$state/archive-before.txt"; else : > "$state/archive-before.txt"; fi
  [[ -d $root/data ]] && echo yes > "$state/data-existed" || echo no > "$state/data-existed"

  echo "building frontend (same-origin API, as in production)..."
  VITE_API_BASE_URL= npm --prefix "$root/frontend" run build > "$state/build.log" 2>&1 ||
    die "frontend build failed; see $state/build.log"

  local proxy_env=(HTTPS_PROXY="$dead_proxy" HTTP_PROXY="$dead_proxy" https_proxy="$dead_proxy" http_proxy="$dead_proxy"
    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost)
  [[ ${FD_VERIFY_ALLOW_FX:-} == 1 ]] && proxy_env=()

  # Blank credentials win over any .env that load_dotenv() finds: it never overrides a set variable.
  ( cd "$root" && exec setsid env \
      BINANCE_API_KEY= BINANCE_API_SECRET= WISE_API_TOKEN= WISE_PROFILE_ID= \
      IBKR_FLEX_TOKEN= IBKR_FLEX_QUERY_ID= \
      FINANCE_DASH_DB_FILE="$state/finance_dash.db" \
      FINANCE_DASH_BACKUP_DIR="$state/backups" \
      "${proxy_env[@]}" \
      "$root/.venv/bin/python" -m uvicorn backend.api:app --host 127.0.0.1 --port "$port" \
      > "$state/server.log" 2>&1 < /dev/null ) &
  local pid=$!
  {
    echo "pid=$pid"
    echo "port=$port"
    echo "url=http://127.0.0.1:$port"
    echo "db=$state/finance_dash.db"
    echo "root=$root"
    echo "revision=$(git -C "$root" rev-parse HEAD)"
    echo "outbound=$([[ ${#proxy_env[@]} -gt 0 ]] && echo blocked || echo fx-allowed)"
  } > "$state/instance.env"

  local url=http://127.0.0.1:$port i
  for i in $(seq 1 60); do
    kill -0 "$pid" 2>/dev/null || die "server exited during startup; see $state/server.log"
    if curl -fsS "$url/dashboard" 2>/dev/null | grep -q '"sources"' &&
      curl -fsS -H 'Accept: text/html' "$url/" 2>/dev/null | grep -q '<title>Finance Dash</title>'; then
      echo "ready: $url (pid $pid, db $state/finance_dash.db)"
      return 0
    fi
    sleep 0.5
  done
  die "not ready after 30 s; see $state/server.log, then run 'control.sh stop $run'"
}

doctor() {
  local ok=0 pid port url db environ
  [[ -f $state/instance.env ]] || die "no instance for run $run (expected $state/instance.env); launch it first"
  pid=$(get pid) port=$(get port) url=$(get url) db=$(get db)
  check() { if eval "$2" 2>/dev/null; then echo "ok    $1"; else echo "FAIL  $1"; ok=1; fi; }

  check "process $pid alive and is our uvicorn" \
    "tr '\0' ' ' < /proc/$pid/cmdline 2>/dev/null | grep -q 'uvicorn backend.api:app --host 127.0.0.1 --port $port'"
  check "port $port listened on by pid $pid" "ss -ltnpH 'sport = :$port' | grep -q 'pid=$pid,'"
  check "GET /health answers ok" "curl -fsS '$url/health' | grep -q '\"ok\"'"
  check "GET / serves the built frontend" "curl -fsS -H 'Accept: text/html' '$url/' | grep -q '<title>Finance Dash</title>'"
  environ=$(tr '\0' '\n' 2>/dev/null < "/proc/$pid/environ")
  check "database is the scratch file $db" "grep -qx 'FINANCE_DASH_DB_FILE=$db' <<< \"\$environ\" && [[ $db == $state/* ]]"
  check "source credentials blank (Binance, Wise, IBKR)" \
    "[[ -n \$environ ]] && ! grep -E '^(BINANCE_API_KEY|BINANCE_API_SECRET|WISE_API_TOKEN|IBKR_FLEX_TOKEN|IBKR_FLEX_QUERY_ID)=.' <<< \"\$environ\" | grep -q ."
  if [[ $(get outbound) == blocked ]]; then
    check "outbound HTTP goes to the dead proxy" "grep -qx 'HTTPS_PROXY=$dead_proxy' <<< \"\$environ\""
  else
    echo "note  outbound HTTP allowed (FD_VERIFY_ALLOW_FX=1): the FX lookup reaches api.frankfurter.dev"
  fi
  check "build is this checkout's HEAD $(get revision | cut -c1-12)" "[[ \$(git -C '$root' rev-parse HEAD) == $(get revision) ]]"
  echo "url   $url"
  echo "db    $db"
  echo "proof $(proof_dir)"
  return $ok
}

browser() {
  # Each run gets its own bridge and an isolated, throwaway Chrome profile. The dead proxy keeps the
  # page from reaching anything but loopback (Chrome never proxies 127.0.0.1), which covers the
  # notes widget's live endpoint on the tailnet.
  local exe=${CHROME_DEVTOOLS_AXI_EXECUTABLE_PATH:-} args="--proxy-server=${dead_proxy#http://}"
  if [[ ${1:-} != stop ]]; then
    [[ -z $exe ]] && exe=$(command -v google-chrome google-chrome-stable 2>/dev/null | head -n1)
    [[ -n $exe && -x $exe ]] || die "no Chrome found; set CHROME_DEVTOOLS_AXI_EXECUTABLE_PATH to a Chrome binary" \
      "(install one with: npx @puppeteer/browsers install chrome@stable --path <dir>)"
  fi
  # Ubuntu's AppArmor only grants Chrome's user-namespace sandbox to /opt/google/chrome; any other
  # binary (Chrome for Testing) aborts with "No usable sandbox" unless the sandbox is turned off.
  # The page is our own loopback app and everything else is unreachable through the dead proxy.
  [[ -n $exe && $(realpath "$exe") != /opt/google/chrome/* ]] && args+=" --no-sandbox"
  CHROME_DEVTOOLS_AXI_SESSION=$browser_session \
    CHROME_DEVTOOLS_AXI_EXECUTABLE_PATH=$exe \
    CHROME_DEVTOOLS_AXI_CHROME_ARGS=$args \
    chrome-devtools-axi "$@"
}

ref() {
  # Snapshot refs are generation-tagged and change after every action, so look the element up by its
  # role and accessible name each time, as printed in a snapshot: button "Sync now", textbox "Note".
  local want=${1:-} line
  [[ -n $want ]] || die "usage: control.sh ref <run-id> '<role> \"<name>\"'"
  # The whole role and name must match: followed by an attribute or the end of the line, so
  # 'button "Save"' does not pick 'button "Save holding"'.
  line=$(browser snapshot --full 2>&1 | awk -v w=" $want" '{
    i = index($0, w); c = substr($0, i + length(w), 1)
    if (i && (c == "" || c == " ")) { print; exit }
  }')
  [[ -n $line ]] || die "no element matching '$want' in the current snapshot"
  sed -E 's/^ *uid=([^ ]+) .*/@\1/' <<< "$line"
}

api() {
  local method=${1:-} path=${2:-} body=${3:-}
  [[ -n $method && -n $path ]] || die "usage: control.sh api <run-id> <METHOD> <path> [json-body]"
  [[ -f $state/instance.env ]] || die "no instance for run $run; launch it first"
  if [[ -n $body ]]; then
    curl -sS -X "$method" -H 'Content-Type: application/json' -d "$body" -w '\nHTTP %{http_code}\n' "$(get url)$path"
  else
    curl -sS -X "$method" -w '\nHTTP %{http_code}\n' "$(get url)$path"
  fi
}

sql() {
  [[ -n ${1:-} ]] || die "usage: control.sh sql <run-id> <query>"
  [[ -f $state/instance.env ]] || die "no instance for run $run; launch it first"
  "$root/.venv/bin/python" -I - "$(get db)" "$1" <<'PY'
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
cur = con.execute(sys.argv[2])
print("|".join(d[0] for d in cur.description or []))
for row in cur:
    print("|".join("" if v is None else str(v) for v in row))
PY
}

stop() {
  local pid port i f
  if [[ -f $state/instance.env ]]; then
    pid=$(get pid) port=$(get port)
    if kill -0 "$pid" 2>/dev/null; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
      for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      kill -0 "$pid" 2>/dev/null && kill -KILL -- "-$pid" 2>/dev/null
    fi
    ss -ltnH "sport = :$port" | grep -q LISTEN && echo "warning: port $port still listening" >&2
    echo "stopped server pid $pid (port $port)"
  else
    echo "no server state for run $run"
  fi

  browser stop > /dev/null 2>&1 && echo "stopped browser session $browser_session"

  if [[ -f $state/archive-before.txt && -d $archive ]]; then
    for f in "$archive"/*; do
      [[ -e $f ]] || continue
      grep -qxF "$(basename "$f")" "$state/archive-before.txt" || { rm -f -- "$f"; echo "removed archived upload $f"; }
    done
    if [[ $(cat "$state/data-existed" 2>/dev/null) == no ]]; then
      rmdir "$archive" "$root/data/csv_archive" 2>/dev/null
      rmdir "$root/data" 2>/dev/null
    fi
  fi

  [[ -d $state ]] && rm -rf -- "$state" && echo "removed scratch state $state"
  echo "proof kept in $(proof_dir)"
}

case $cmd in
  launch) launch ;;
  doctor) doctor ;;
  url) [[ -f $state/instance.env ]] || die "no instance for run $run"; get url ;;
  proof-dir) proof_dir ;;
  browser) browser "$@" ;;
  ref) ref "$@" ;;
  api) api "$@" ;;
  sql) sql "$@" ;;
  stop) stop ;;
  *) die "unknown command '$cmd'" ;;
esac
