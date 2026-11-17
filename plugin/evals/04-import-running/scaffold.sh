#!/usr/bin/env bash
# A task that is already running: its plan in plan.md, an empty task folder, no graph yet.
set -euo pipefail
mkdir -p .tasks/SHOP
cat > plan.md <<'EOF'
# Online shop: plan

Session 01 (backend) does A1, then A2. Session 02 (mail) does A3.

- [x] A1 Cart. Done and merged.
- [ ] A2 Checkout. Needs A1. Code is written; waiting for code review by a teammate.
- [ ] A3 Order emails. Needs A2 merged. Not started.
EOF
