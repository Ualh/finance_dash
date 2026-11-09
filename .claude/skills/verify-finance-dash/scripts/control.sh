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
[[ $run =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]] ||
  die "run-id must start with a letter or digit and contain only letters, digits, '.', '_' and '-'"
shift 2

root=$(git -C "$(dirname "$0")" rev-parse --show-toplevel) || die "not inside a git checkout"
runs=${TMPDIR:-/tmp}/finance-dash-verify
state=$runs/$run
archive=$root/data/csv_archive/neon
browser_session=fdverify-$run
dead_proxy=http://127.0.0.1:9
# Every variable that would let the instance reach a real account. All are set empty at launch.
credentials=(BINANCE_API_KEY BINANCE_API_SECRET WISE_API_TOKEN WISE_PROFILE_ID IBKR_FLEX_TOKEN IBKR_FLEX_QUERY_ID)

# The state dir sits in a shared temp dir: only trust one this user owns.
[[ ! -e $state || -O $state ]] || die "$state is not owned by $(id -un); refusing to use it"

# recorded <key>: a value launch wrote to the state file.
recorded() { sed -n "s/^$1=//p" "$state/instance.env" 2>/dev/null | head -n1; }

require_instance() { [[ -f $state/instance.env ]] || die "no instance for run $run (no $state/instance.env); launch it first"; }

# is_our_server <pid> <port>: the pid is still the uvicorn launch started, not a reused pid.
is_our_server() {
  tr '\0' ' ' 2>/dev/null < "/proc/$1/cmdline" | grep -q "uvicorn backend.api:app --host 127.0.0.1 --port $2 "
}

serves_frontend() { curl -fsS -H 'Accept: text/html' "$1/" 2>/dev/null | grep -q '<title>Finance Dash</title>'; }

# Fingerprint of the code under test: HEAD plus any uncommitted change to tracked files.
tree_state() { { git -C "$root" rev-parse HEAD; git -C "$root" diff HEAD; } | sha256sum | cut -c1-16; }

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

# One live run per checkout: stop tells this run's Neon uploads apart from the files present at
# launch, so a second run uploading into the same archive at the same time would lose its files.
refuse_second_run() {
  local other
  for other in "$runs"/*/instance.env; do
    [[ -f $other && $other != "$state/instance.env" ]] || continue
    [[ $(sed -n 's/^root=//p' "$other") == "$root" ]] || continue
    is_our_server "$(sed -n 's/^pid=//p' "$other")" "$(sed -n 's/^port=//p' "$other")" &&
      die "run $(basename "$(dirname "$other")") is still live in this checkout; stop it first"
  done
  return 0
}

free_port() {
  python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])'
}

proof_path() { echo "${FD_PROOF_DIR:-$root/data/verify-proof/$run}"; }

launch() {
  refuse_live_checkout
  refuse_second_run
  [[ -e $state/instance.env ]] && die "run $run already has state in $state; run 'control.sh stop $run' first"
  [[ -x $root/.venv/bin/python ]] ||
    die "no $root/.venv; create it: python3 -m venv $root/.venv && $root/.venv/bin/pip install -r $root/requirements.txt"
  [[ -d $root/frontend/node_modules ]] || die "no frontend/node_modules; run: npm --prefix $root/frontend ci"

  local port=${FD_VERIFY_PORT:-$(free_port)}
  case $port in 8000 | 8001 | 5173) die "port $port belongs to the dev or live app; pick another" ;; esac
  ss -ltn "sport = :$port" | grep -q LISTEN && die "port $port is already in use"

  mkdir -p "$state" && chmod 700 "$state" || die "cannot create $state"
  # Neon CSVs already archived in this checkout stay; stop removes only the ones this run adds.
  if [[ -d $archive ]]; then ls -1 "$archive" > "$state/archive-before.txt"; else : > "$state/archive-before.txt"; fi
  if [[ -d $root/data ]]; then echo yes > "$state/data-existed"; else echo no > "$state/data-existed"; fi

  echo "building frontend (same-origin API, as in production)..."
  VITE_API_BASE_URL= npm --prefix "$root/frontend" run build > "$state/build.log" 2>&1 ||
    die "frontend build failed; see $state/build.log"

  local proxy_env=(HTTPS_PROXY="$dead_proxy" HTTP_PROXY="$dead_proxy" https_proxy="$dead_proxy" http_proxy="$dead_proxy"
    NO_PROXY=127.0.0.1,localhost no_proxy=127.0.0.1,localhost)
  [[ ${FD_VERIFY_ALLOW_FX:-} == 1 ]] && proxy_env=()
  local blank=() name
  for name in "${credentials[@]}"; do blank+=("$name="); done

  # Blank credentials win over any .env that load_dotenv() finds: it never overrides a set variable.
  ( cd "$root" && exec setsid env "${blank[@]}" \
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
    echo "tree=$(tree_state)"
    echo "outbound=$([[ ${#proxy_env[@]} -gt 0 ]] && echo blocked || echo fx-allowed)"
  } > "$state/instance.env"

  local url=http://127.0.0.1:$port i
  for i in $(seq 1 60); do
    kill -0 "$pid" 2>/dev/null || die "server exited during startup; see $state/server.log, then run 'control.sh stop $run'"
    if curl -fsS "$url/dashboard" 2>/dev/null | grep -q '"sources"' && serves_frontend "$url"; then
      echo "ready: $url (pid $pid, db $state/finance_dash.db)"
      return 0
    fi
    sleep 0.5
  done
  die "not ready after 30 s; see $state/server.log, then run 'control.sh stop $run'"
}

doctor() {
  require_instance
  local failed=0 pid port url db environ name
  pid=$(recorded pid) port=$(recorded port) url=$(recorded url) db=$(recorded db)
  check() { if "${@:2}"; then echo "ok    $1"; else echo "FAIL  $1"; failed=1; fi; }
  has_env() { grep -qxF "$1" <<< "$environ"; }
  creds_blank() {
    [[ -n $environ ]] || return 1
    for name in "${credentials[@]}"; do grep -qx "$name=" <<< "$environ" || return 1; done
  }

  check "process $pid alive and is our uvicorn" is_our_server "$pid" "$port"
  check "port $port listened on by pid $pid" eval "ss -ltnpH 'sport = :$port' | grep -q 'pid=$pid,'"
  check "GET /health answers ok" eval "curl -fsS '$url/health' 2>/dev/null | grep -q '\"ok\"'"
  check "GET / serves the built frontend" serves_frontend "$url"
  environ=$(tr '\0' '\n' 2>/dev/null < "/proc/$pid/environ")
  check "database is the scratch file $db" eval "has_env 'FINANCE_DASH_DB_FILE=$db' && [[ '$db' == '$state'/* ]]"
  check "source credentials set and blank (Binance, Wise, IBKR)" creds_blank
  if [[ $(recorded outbound) == blocked ]]; then
    check "outbound HTTP goes to the dead proxy" has_env "HTTPS_PROXY=$dead_proxy"
  else
    echo "note  outbound HTTP allowed (FD_VERIFY_ALLOW_FX=1): the FX lookup reaches api.frankfurter.dev"
  fi
  check "built from this checkout as it is now (HEAD $(recorded revision | cut -c1-12), no edits since launch)" \
    eval "[[ \$(tree_state) == '$(recorded tree)' ]]"
  echo "url   $url"
  echo "db    $db"
  echo "proof $(proof_path)"
  return $failed
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
  local want=${1:-} snap line
  [[ -n $want ]] || die "usage: control.sh ref <run-id> '<role> \"<name>\"'"
  snap=$(browser snapshot --full) || die "snapshot failed"
  # The whole role and name must match: followed by an attribute or the end of the line, so
  # 'button "Save"' does not pick 'button "Save holding"'.
  line=$(awk -v w=" $want" '/^ *uid=/ {
    i = index($0, w); c = substr($0, i + length(w), 1)
    if (i && (c == "" || c == " ")) { print; exit }
  }' <<< "$snap")
  [[ -n $line ]] || die "no element matching '$want' in the current snapshot"
  sed -E 's/^ *uid=([^ ]+) .*/@\1/' <<< "$line"
}

api() {
  local method=${1:-} path=${2:-} body=${3:-}
  [[ -n $method && -n $path ]] || die "usage: control.sh api <run-id> <METHOD> <path> [json-body]"
  require_instance
  local args=(-sS -X "$method" -w '\nHTTP %{http_code}\n')
  [[ -n $body ]] && args+=(-H 'Content-Type: application/json' -d "$body")
  curl "${args[@]}" "$(recorded url)$path"
}

sql() {
  [[ -n ${1:-} ]] || die "usage: control.sh sql <run-id> <query>"
  require_instance
  "$root/.venv/bin/python" -I - "$(recorded db)" "$1" <<'PY'
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
    pid=$(recorded pid) port=$(recorded port)
    # Only signal the pid if it is still the server launch started: after a crash the pid may
    # belong to an unrelated process by now.
    if is_our_server "$pid" "$port"; then
      kill -TERM -- "-$pid" 2>/dev/null || kill -TERM "$pid"
      for i in $(seq 1 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.25; done
      is_our_server "$pid" "$port" && kill -KILL -- "-$pid"
      echo "stopped server pid $pid (port $port)"
    else
      echo "server pid $pid (port $port) was not running"
    fi
    ss -ltnH "sport = :$port" | grep -q LISTEN && echo "warning: port $port still listening" >&2
  else
    echo "no server state for run $run"
  fi

  if browser stop > /dev/null 2>&1; then echo "stopped browser session $browser_session"; fi

  if [[ -f $state/archive-before.txt && -d $archive ]]; then
    for f in "$archive"/*; do
      [[ -e $f ]] || continue
      grep -qxF "$(basename "$f")" "$state/archive-before.txt" || { rm -f -- "$f"; echo "removed archived upload $f"; }
    done
    # Remove the archive dirs only if this run created them and they are empty again.
    if [[ $(cat "$state/data-existed" 2>/dev/null) == no ]]; then
      rmdir -- "$archive" "$root/data/csv_archive" "$root/data" 2>/dev/null || echo "kept $root/data (not empty)"
    fi
  fi

  if [[ -d $state ]]; then rm -rf -- "$state" && echo "removed scratch state $state"; fi
  echo "proof kept in $(proof_path)"
}

case $cmd in
  launch) launch ;;
  doctor) doctor ;;
  url) require_instance; recorded url ;;
  proof-dir) mkdir -p "$(proof_path)" && proof_path ;;
  browser) browser "$@" ;;
  ref) ref "$@" ;;
  api) api "$@" ;;
  sql) sql "$@" ;;
  stop) stop ;;
  *) die "unknown command '$cmd'" ;;
esac
