#!/usr/bin/env bash
# A running task SHOP: A1 Cart in progress (plan finished), A2 Checkout after A1's code, A3 after A2.
set -euo pipefail
mkdir -p .tasks/SHOP
cat > .tasks/SHOP/taskgraph.js <<'EOF'
// Task graph data. Written by fm (Flagman); do not edit by hand.
window.TASKGRAPH = {
 "version": 1,
 "lang": "en",
 "task": {"key": "SHOP", "title": "Online shop", "links": [], "due": null, "updated": "2026-11-17T18:34", "rev": 5},
 "stages": ["plan", "code", "review", "PR", "merged", "done"],
 "groups": [],
 "sessions": [],
 "items": [
  {"id": "A1", "title": "Cart", "group": null, "session": null, "stage": 0, "status": "doing", "wait": "",
   "deps": [], "summary": "add, remove and list cart items", "details": [], "links": [], "files": []},
  {"id": "A2", "title": "Checkout", "group": null, "session": null, "stage": -1, "status": "todo", "wait": "",
   "deps": [{"id": "A1", "stage": 1, "note": ""}], "summary": "", "details": [], "links": [], "files": []},
  {"id": "A3", "title": "Order emails", "group": null, "session": null, "stage": -1, "status": "todo", "wait": "",
   "deps": [{"id": "A2", "note": ""}], "summary": "", "details": [], "links": [], "files": []}
 ],
 "conflicts": []
};
EOF
