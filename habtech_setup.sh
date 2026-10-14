#!/bin/bash
# NHDW self-healing setup. Safe to run more than once -- every stage
# checks whether it already succeeded before doing anything, and if a
# stage is broken (partial venv, missing binary) it wipes just that
# piece and rebuilds it rather than erroring out. Ends with a doctor
# report so you know exactly what's usable before a demo, instead of
# hoping.
#
# deliberately NOT `set -e` at the top level: a hard `set -e` means one
# optional, non-critical failure (e.g. step 10's python3.11 install)
# kills the whole script, including pieces that hadn't run yet. Instead,
# each stage is a function that returns 0/1, gets called, and the
# result is tracked -- so one bad stage never silently prevents good
# stages after it from running.

HABTECH_HOME="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export HABTECH_HOME
cd "$HABTECH_HOME"
echo "using $HABTECH_HOME as this copy's home"
echo ""

STATUS_OK=()
STATUS_FAIL=()
STATUS_SKIP=()

mark_ok()   { STATUS_OK+=("$1");   echo "  OK: $1"; }
mark_fail() { STATUS_FAIL+=("$1"); echo "  FAILED: $1"; }
mark_skip() { STATUS_SKIP+=("$1"); echo "  already OK, skipping: $1"; }

# ---------------------------------------------------------------------
# stage: system packages
# ---------------------------------------------------------------------
stage_system_packages() {
  echo "== system packages =="
  if command -v docker >/dev/null 2>&1 && command -v pip3 >/dev/null 2>&1; then
    mark_skip "docker + pip already present"
  else
    sudo apt update -qq
    sudo apt install -y docker.io python3-pip -qq
  fi
  sudo systemctl enable docker >/dev/null 2>&1 || true
  sudo systemctl start docker >/dev/null 2>&1 || true
  if command -v docker >/dev/null 2>&1; then
    mark_ok "docker + pip"
  else
    mark_fail "docker + pip -- install manually: sudo apt install docker.io python3-pip"
  fi
}

# ---------------------------------------------------------------------
# stage: main flat pip install (system-wide)
# ---------------------------------------------------------------------
# tested directly against PyPI: this exact list resolves cleanly
# together on Python 3.12 (pandas 3.x, numpy 2.x, meltano 4.x, pyspark
# 4.x, linktransformer -- no conflicts). NOT forcing --only-binary here:
# pyspark has never published a wheel on PyPI at all (source-only, pure
# Python + bundled jars, trivial to "build", doesn't hit the
# pkg_resources bug below) -- forcing wheel-only would make pyspark fail
# with "no matching distribution found", worse than what it avoids.
MAIN_PACKAGES="meltano pandas openpyxl psycopg2-binary duckdb pyspark google-genai requests linktransformer clickhouse-connect minio"

stage_main_packages() {
  echo "== main pipeline packages (system-wide) =="
  # self-check: are the actual import names for these packages already
  # importable? (package name != import name for several of these)
  if python3 -c "import pandas, openpyxl, psycopg2, duckdb, pyspark, google.genai, requests, linktransformer, clickhouse_connect, minio" >/dev/null 2>&1 \
     && command -v meltano >/dev/null 2>&1; then
    mark_skip "main pipeline packages"
    return 0
  fi
  if pip install $MAIN_PACKAGES --break-system-packages -q; then
    mark_ok "main pipeline packages"
  else
    mark_fail "main pipeline packages -- see output above"
  fi
}

# ---------------------------------------------------------------------
# stage: dbt_venv (dbt-postgres + dbt-clickhouse -- steps 1-9)
# ---------------------------------------------------------------------
pick_python() {
  for candidate in python3.12 python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      echo "$candidate"
      return 0
    fi
  done
  echo "python3"
}

stage_dbt_venv() {
  echo "== dbt_venv (dbt-postgres + dbt-clickhouse) =="
  # self-check: does a working dbt already exist here?
  if "$HABTECH_HOME/dbt_venv/bin/dbt" --version >/dev/null 2>&1; then
    mark_skip "dbt_venv"
    return 0
  fi
  # broken/partial venv from a previous crashed run -- wipe and rebuild
  # rather than erroring on a half-built directory
  if [ -d "$HABTECH_HOME/dbt_venv" ]; then
    echo "  dbt_venv exists but isn't working -- rebuilding it"
    rm -rf "$HABTECH_HOME/dbt_venv"
  fi
  local py; py="$(pick_python)"
  echo "  building with $py"
  "$py" -m venv "$HABTECH_HOME/dbt_venv"
  "$HABTECH_HOME/dbt_venv/bin/pip" install --upgrade pip -q
  # --only-binary=:all: specifically here: dbt-postgres and
  # dbt-clickhouse both DO have real prebuilt wheels, and forcing
  # wheel-only avoids the "ModuleNotFoundError: No module named
  # 'pkg_resources'" crash -- pip builds anything lacking a matching
  # wheel inside its OWN temporary isolated sandbox (not this venv),
  # and that sandbox's setuptools can end up missing pkg_resources,
  # breaking a legacy source build before it even starts compiling.
  # tested directly: these two together resolve and install clean,
  # every time, with this flag.
  # IMPORTANT: dbt-postgres-python is NEVER installed here -- see
  # stage_dbt_python_venv below for why combining them breaks this
  # exact install.
  if "$HABTECH_HOME/dbt_venv/bin/pip" install --only-binary=:all: dbt-postgres dbt-clickhouse -q \
     && "$HABTECH_HOME/dbt_venv/bin/dbt" --version >/dev/null 2>&1; then
    mark_ok "dbt_venv"
  else
    mark_fail "dbt_venv -- steps 1-9 will not work until this is fixed"
  fi
}

# ---------------------------------------------------------------------
# stage: dbt_python_venv (dbt-postgres-python -- step 10 ONLY, optional)
# ---------------------------------------------------------------------
# root cause, confirmed against PyPI's own metadata, not guessed:
#   - dbt-postgres-python hard-pins pandas<2.0
#   - pandas has never published a wheel for that line on Python 3.12,
#     only 3.10/3.11 -- so this package needs an OLDER python, its own
#     venv, separate from dbt_venv above (which is fine on 3.12).
#   - separately: the dbt Python model used to import linktransformer
#     in-process, and linktransformer needs pandas>=2.0 -- incompatible
#     with dbt-postgres-python's pandas<2.0 in one process, on ANY
#     python version. Fixed: fact_linkage_scored.py now reads a CSV
#     that linktransformer_examples/export_scored_matches.py writes
#     separately (in the main venv above), so this venv never needs to
#     import linktransformer at all. See DBT_PYTHON_MODELS_NOTE.md.
# entirely optional -- steps 1-9 never depend on this succeeding.
stage_dbt_python_venv() {
  echo "== dbt_python_venv (dbt-postgres-python, step 10 only, optional) =="
  if "$HABTECH_HOME/dbt_python_venv/bin/dbt" --version >/dev/null 2>&1; then
    mark_skip "dbt_python_venv"
    return 0
  fi
  if [ -d "$HABTECH_HOME/dbt_python_venv" ]; then
    echo "  dbt_python_venv exists but isn't working -- rebuilding it"
    rm -rf "$HABTECH_HOME/dbt_python_venv"
  fi

  local dbt_py_old=""
  for candidate in python3.11 python3.10; do
    if command -v "$candidate" >/dev/null 2>&1; then
      dbt_py_old="$candidate"
      break
    fi
  done

  if [ -z "$dbt_py_old" ]; then
    echo "  python3.10/3.11 not found -- attempting to install python3.11"
    sudo apt install -y python3.11 python3.11-venv -qq 2>/dev/null || {
      sudo apt install -y software-properties-common -qq 2>/dev/null
      sudo add-apt-repository -y ppa:deadsnakes/ppa 2>/dev/null
      sudo apt update -qq 2>/dev/null
      sudo apt install -y python3.11 python3.11-venv -qq 2>/dev/null
    }
    command -v python3.11 >/dev/null 2>&1 && dbt_py_old="python3.11"
  fi

  if [ -z "$dbt_py_old" ]; then
    mark_skip "dbt_python_venv (no python3.10/3.11 available -- step 10 stays disabled, steps 1-9 unaffected)"
    return 0
  fi

  echo "  building with $dbt_py_old"
  "$dbt_py_old" -m venv "$HABTECH_HOME/dbt_python_venv"
  "$HABTECH_HOME/dbt_python_venv/bin/pip" install --upgrade pip -q
  if "$HABTECH_HOME/dbt_python_venv/bin/pip" install --only-binary=:all: dbt-postgres-python -q \
     && "$HABTECH_HOME/dbt_python_venv/bin/dbt" --version >/dev/null 2>&1; then
    mark_ok "dbt_python_venv (step 10 available)"
  else
    mark_skip "dbt_python_venv (install failed even on $dbt_py_old -- step 10 stays disabled, steps 1-9 unaffected, see DBT_PYTHON_MODELS_NOTE.md)"
  fi
}

# ---------------------------------------------------------------------
# stage: meltano taps/targets
# ---------------------------------------------------------------------
stage_meltano() {
  echo "== meltano taps/targets =="
  cd "$HABTECH_HOME/meltano_project"
  if meltano config tap-csv list >/dev/null 2>&1 && meltano config target-postgres list >/dev/null 2>&1; then
    mark_skip "meltano tap-csv + target-postgres"
    cd "$HABTECH_HOME"
    return 0
  fi
  if meltano add tap-csv && meltano add target-postgres; then
    mark_ok "meltano tap-csv + target-postgres"
  else
    mark_fail "meltano tap-csv + target-postgres"
  fi
  cd "$HABTECH_HOME"
}

# ---------------------------------------------------------------------
# run every stage -- each one independently, none blocks the next
# ---------------------------------------------------------------------
stage_system_packages
echo ""
stage_main_packages
echo ""
stage_dbt_venv
echo ""
stage_dbt_python_venv
echo ""
stage_meltano
echo ""

# ---------------------------------------------------------------------
# doctor report -- what you actually have, before you're relying on it
# live
# ---------------------------------------------------------------------
echo "======================================================================"
echo "SETUP REPORT"
echo "======================================================================"
for s in "${STATUS_OK[@]}";   do echo "  [OK]      $s"; done
for s in "${STATUS_SKIP[@]}"; do echo "  [SKIPPED] $s (already working, or intentionally optional)"; done
for s in "${STATUS_FAIL[@]}"; do echo "  [FAILED]  $s"; done
echo ""

if [ "${#STATUS_FAIL[@]}" -eq 0 ]; then
  echo "Everything required is in place."
else
  echo "${#STATUS_FAIL[@]} stage(s) need attention before the demo -- see FAILED lines above."
fi

echo ""
echo "every new terminal window for the demo needs this line run first:"
echo "    export HABTECH_HOME=$HABTECH_HOME"
echo ""
echo "then run NHDW_Demo_Commands_v3.txt top to bottom:"
echo "  - steps 1-9: use dbt_venv/bin/dbt"
echo "  - step 10 (optional): use dbt_python_venv/bin/dbt, only if that stage above says OK"
echo ""
echo "re-run this script any time -- it only redoes what's actually broken or missing."
