# Sourced by launchers. Sets the bash array PY to the first Python 3.9+ found.
# Callers run: "${PY[@]}" script.py args
PY=()
for _cand in "py -3" "python3" "python"; do
    read -r -a _try <<< "$_cand"
    if "${_try[@]}" -c "import sys; sys.exit(sys.version_info < (3, 9))" >/dev/null 2>&1; then
        PY=("${_try[@]}")
        break
    fi
done
unset _cand _try
if [ "${#PY[@]}" -eq 0 ]; then
    echo "error: Python 3.9+ not found (tried py -3, python3, python)" >&2
    exit 127
fi
