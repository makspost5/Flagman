// Task graph data. Written by fm (Flagman); do not edit by hand.
window.TASKGRAPH = {
 "version": 1,
 "lang": "en",
 "task": {
  "key": "SHOP-1",
  "title": "Web shop release",
  "links": [
   {
    "label": "Release notes",
    "href": "https://example.com/release-notes"
   }
  ],
  "due": "2026-12-15",
  "updated": "2026-11-16T09:38",
  "rev": 20
 },
 "stages": [
  "plan",
  "code",
  "review",
  "PR",
  "merged",
  "done"
 ],
 "groups": [
  {
   "id": "pay",
   "title": "Payments",
   "estimate": "3 days"
  },
  {
   "id": "cat",
   "title": "Catalog",
   "estimate": "2 days"
  },
  {
   "id": "ops",
   "title": "Release ops",
   "estimate": "1 day"
  }
 ],
 "sessions": [
  {
   "id": "01",
   "name": "payments",
   "dir": "sessions/01-payments",
   "note": "Gateway integration",
   "queue": [
    "P2",
    "P3"
   ]
  },
  {
   "id": "02",
   "name": "catalog",
   "dir": "sessions/02-catalog",
   "note": "Needs a decision on search",
   "queue": [
    "C1",
    "C2",
    "C3"
   ]
  },
  {
   "id": "03",
   "name": "ops",
   "dir": "sessions/03-ops",
   "note": "",
   "queue": [
    "O2",
    "O3"
   ]
  }
 ],
 "items": [
  {
   "id": "P1",
   "title": "Payment gateway client",
   "group": "pay",
   "session": "01",
   "stage": 5,
   "status": "done",
   "wait": "",
   "deps": [],
   "summary": "Client library merged",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "P2",
   "title": "Checkout flow",
   "group": "pay",
   "session": "01",
   "stage": 1,
   "status": "doing",
   "wait": "",
   "deps": [
    {
     "id": "P1",
     "note": ""
    }
   ],
   "summary": "Cart to payment screen",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "P3",
   "title": "Refunds",
   "group": "pay",
   "session": "01",
   "stage": -1,
   "status": "todo",
   "wait": "",
   "deps": [
    {
     "id": "P2",
     "note": ""
    }
   ],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "C1",
   "title": "Product search index",
   "group": "cat",
   "session": "02",
   "stage": 0,
   "status": "wait-me",
   "wait": "Pick the search engine: hosted or self-managed",
   "deps": [],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "C2",
   "title": "Category pages",
   "group": "cat",
   "session": "02",
   "stage": 2,
   "status": "doing",
   "wait": "",
   "deps": [],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "C3",
   "title": "Search UI",
   "group": "cat",
   "session": "02",
   "stage": -1,
   "status": "todo",
   "wait": "",
   "deps": [
    {
     "id": "C1",
     "note": ""
    }
   ],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "O1",
   "title": "Staging environment",
   "group": "ops",
   "session": "03",
   "stage": 5,
   "status": "done",
   "wait": "",
   "deps": [],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "O2",
   "title": "Load test",
   "group": "ops",
   "session": "03",
   "stage": -1,
   "status": "todo",
   "wait": "",
   "deps": [
    {
     "id": "P2",
     "note": ""
    },
    {
     "id": "C2",
     "note": ""
    }
   ],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  },
  {
   "id": "O3",
   "title": "Release checklist",
   "group": "ops",
   "session": "03",
   "stage": -1,
   "status": "todo",
   "wait": "",
   "deps": [
    {
     "id": "O2",
     "note": ""
    },
    {
     "id": "P3",
     "note": ""
    },
    {
     "id": "C3",
     "note": ""
    }
   ],
   "summary": "",
   "details": [],
   "links": [],
   "files": []
  }
 ],
 "conflicts": [
  {
   "a": "P2",
   "b": "C2",
   "why": "Both change the product card component"
  }
 ]
};
