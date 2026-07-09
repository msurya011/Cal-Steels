# Developer Handover — "Steel-ghost" (steelgenie) Codebase
**Date:** 2026-07-07 · **Basis:** static analysis of repo `Steel-ghost/steelgenie` (backend, frontend, infra). Observations come only from the source; anything not in the repo is marked **[Rec]** (recommendation).

---

## 1. Current Architecture (observed)

```
steelgenie/
├── backend/    FastAPI monolith (main.py, 5,530 lines) + CV/extraction modules (Python)
├── frontend/   Next.js 16 / React 19 / TypeScript app (App Router)
└── infra/      Supabase SQL migration (001_initial.sql)
```

- **Backend**: single FastAPI app. PDF handling via PyMuPDF (fitz), imaging via PIL/NumPy, optional OpenCV raster detection (`detection_cv.py`), a 4-layer brace classifier (`brace_classifier.py`, 1,323 lines, feature-flagged by `BRACE_EXTRACTION` env var), 3D model builder (`structural_schema.py` + `structural_reconstruction.py` — converts 2D members to a Y-up Three.js-style node/member/connectivity JSON with floor elevations and node snapping). Optional Supabase client (guarded import). CORS enabled. Runs with uvicorn on :8000.
- **Endpoints** (all in `main.py`): `GET /health`, `POST /upload` (saves file to local `UPLOAD_DIR`, returns base64 preview + per-page thumbnails), `GET /page-image/{filename}/{page}`, `POST /analyse` (core pipeline), `GET /projects` (Supabase), `POST /save-project` + `GET /saved-projects` (**local JSON file** `saved_projects.json`), `POST /model` (full extraction → 3D model JSON).
- **Extraction pipeline** (`/analyse`): text extraction (vector or OCR for raster), plan-boundary detection (excludes schedules/notes/title block), column-symbol detection from vector paths, grid-line extraction, profile/callout extraction (`extract_profiles`), member classification (`classify_member`), beam span-line detection with direction inference, raster Hough fallback, schedule-zone detection, rotation handling (90°/270° mediabox fix), optional brace extraction with confidence levels and dedup.
- **Frontend**: four routes — `/` (the working takeoff UI: a 1,963-line client component with upload/drag-drop, page thumbnails, scale picker, status (not_set/estimating/built), member overlay with hover tooltips, context-menu member correction/removal, zoom/pan/ruler/marker/crop tools, undo stack, Plans|BOM tabs, save/open project modals), `/dashboard` (Supabase-backed project list + create modal + auth session/sign-out), `/(auth)/login` (Supabase email auth), plus `lib/api.ts` (JWT-injecting fetch wrapper) and `lib/supabase.ts`.
- **Database** (`001_initial.sql`): `projects`, `drawings` (with `r2_key` for Cloudflare R2), `members`, `jobs` — all UUID PKs, full RLS policies chained to `auth.users`.
- **Quality tooling**: `eval_harness.py` — a genuinely good regression harness measuring beams/columns/phantoms/overshoot/duplicates per registered sheet against a saved baseline; `eval_cases.json`/`eval_baseline.json`; verification reports (`BRACE_INTEGRATION_REPORT.md`: 8/8 beam-stability pass, 100 braces across 5 PDFs, +0.13 s avg overhead; `BRACE_DEDUP_REPORT.md`).

### Key architectural disconnects (observed)
1. **Two parallel apps**: the real takeoff workflow (`/`) talks to the FastAPI backend **without any authentication** and persists to a local JSON file; the auth'd Supabase world (`/login`, `/dashboard`, migration, `api.ts`) is wired but unused by the takeoff UI.
2. **Phantom API**: `api.ts#uploadDrawing` calls `POST /projects/{id}/upload` — that endpoint does not exist in `main.py`. The `drawings.r2_key` column implies R2 object storage, but no R2/boto3 code exists.
3. **Lost code**: `.next` build artifacts reference deleted routes (`/projects`, `/projects/new`, `/projects/[id]`) and a deleted `components/StructuralViewer3D.tsx`; backend contains `recovered_main*.py` and `scratch/recover_*.py`. A 3D viewer and project pages existed and were lost — only `/model` (backend) survives. Recovering or rewriting these is a priority.
4. **Repo hygiene**: logs, `.env` (with secrets), debug scripts (`_debug_*`), generated PNG/JPG outputs, and `.next/` are committed.

## 2. Feature Inventory

| Feature | Status |
|---|---|
| PDF upload, page thumbnails, page preview | **Complete** (local disk, base64 transport) |
| Member extraction: beams (vector+raster), columns, joists, grids, schedules exclusion, rotation | **Complete & regression-tested** |
| Unlabeled beam detection; brace extraction (elevations + plans, confidence, dedup) | **Complete, feature-flagged** |
| Overlay UI: tooltips, correction, delete, zoom/pan, ruler, marker, crop, undo | **Complete** |
| Scale selection; page status | **Complete** (manual only) |
| BOM tab | **Partial** — UI tab exists; summary counts (bolts, camber, studs, moment connections) computed; no piecemarking, weights, grades, or export |
| 3D model generation (`/model`) | **Backend complete; frontend viewer lost** |
| Save/open projects | **Partial** — local JSON, no auth, no multi-page persistence |
| Auth (Supabase email), dashboard, project CRUD | **Partial** — isolated from takeoff UI |
| DB schema + RLS, jobs table | **Schema only** — backend never writes drawings/members/jobs |
| Cloud storage (R2), async jobs, exports (KISS/EPM/IFC/PDF), connection design/config, column & brace schedulers, company admin/roles, notifications | **Missing** |

## 3. Module-by-Module Gap Analysis

- **backend/main.py** — monolithic: HTTP layer, CV pipeline, geometry, persistence all in one file. Gaps: no auth middleware, no job queue (synchronous `/analyse`, long-running), no Supabase writes, filename-keyed uploads (collision + path-traversal risk via `filename` in URL/body).
- **brace_classifier.py / detection_cv.py / structural_*.py** — cohesive, documented, testable. Gap: brace flag default-off; `/model` bypasses flag (inconsistent).
- **frontend/app/page.tsx** — functional but a 1,963-line monolith; hardcoded `http://localhost:8000` **[verify]**; no auth header usage; state should be decomposed.
- **dashboard/login** — fine, but orphaned; project create writes to Supabase while takeoff saves to JSON — two sources of truth.
- **infra** — single migration; missing tables for pages, configurations, BOM items, exports, and the whole company/roles layer needed for the target product.

## 4. Comparison to Target Product (feature-level; from the SRS in `SRS_Internal_Steel_Estimation_Platform.md`)

Present here: upload/analysis, member overlay editing, scale, statuses, basic BOM counts, 3D model JSON. Missing vs. target: engineering configuration (ASD/LRFD, reactions, connection types, materials, size priorities), build engine with piecemarks/connection material, column scheduler, braced-frame scheduler, full BOM grid with filters/fields, exports (Tekla EPM, KISS, IFC, marked-up PDF), 3D viewer, folders/sharing/company admin/licenses, notifications.

## 5. Screen-by-Screen Specs & UI/UX Recommendations **[Rec]**

1. **Login** — keep; add MFA + SSO later.
2. **Projects home** (rebuild lost pages): card/table list, search, status badges, create modal (name, number, standard, units) → replaces both `/dashboard` and JSON save/open modals.
3. **Takeoff workspace** (`/projects/[id]`): split current `/` monolith into left page-rail (thumbnails, scale, T.O.S., status), canvas (overlay, tools), right properties panel (member edit, bulk ops). Add: keyboard shortcuts, member search, "Need review" filter, autosave indicator, per-page Build button with progress.
4. **BOM screen**: real grid (piecemark, qty, section, length, grade, weight) with filters, column chooser, CSV/KISS export.
5. **3D viewer**: restore `StructuralViewer3D` (Three.js) fed by `/model`; color by member type.
6. UX fixes: replace base64 image payloads with URL-served tiles (faster loads); optimistic member edits; toast on analysis completion; empty-state guidance.

## 6. Component Hierarchy **[Rec]**

```
AppShell → ProjectsHome{ProjectCard, CreateProjectModal}
         → Workspace{PageRail, CanvasToolbar, PlanCanvas(OverlayLayer, ToolLayer),
                     PropertiesPanel, BomView(FilterBar, DataGrid, ExportMenu),
                     Viewer3D, StatusBar}
Shared: api client (extend lib/api.ts), useProject/usePage stores (Zustand), Toast
```

## 7. Backend Service Architecture **[Rec]**

Keep one FastAPI service but restructure into packages: `api/` (routers: auth, projects, drawings, analysis, model, bom, exports), `core/` (config, security), `extraction/` (existing CV modules), `models/` (SQLAlchemy or supabase repos), `workers/` (RQ/Celery consuming the existing `jobs` table for analyse/build/export). Verify Supabase JWTs in a dependency; store files in R2/S3 using the already-modeled `r2_key`. Split `/analyse` into enqueue + status endpoints (WebSocket or polling on `jobs`).

## 8. Database Schema Recommendations **[Rec]**

Extend `001_initial.sql`: add `pages` (per-page scale/T.O.S./status — currently page state lives only in the client), `configurations` (project engineering settings JSONB), `bom_items`, `export_jobs`, `annotations`; add `updated_at` triggers and indexes on FKs; later `companies` + role column for multi-user. Migrate `saved_projects.json` into `projects/drawings/members` and delete the file path.

## 9. API Specification **[Rec]** (target)

```
POST /auth handled by Supabase
GET/POST /projects ; GET/PATCH/DELETE /projects/{id}
POST /projects/{id}/drawings (multipart → R2)           GET /drawings/{id}/pages/{n}/image
POST /drawings/{id}/pages/{n}/analyse → {job_id}        GET /jobs/{id}
GET/PATCH/DELETE /pages/{id}/members (+bulk)            PUT /projects/{id}/configuration
POST /projects/{id}/build → job                          GET /projects/{id}/bom?filters
POST /projects/{id}/exports {format: csv|kiss|epm|ifc|pdf}   GET /projects/{id}/model
```

## 10. Coding Guidelines **[Rec]**

Python: ruff + black, type hints, pydantic models per router, no prints → structlog; ban `_debug_*` in `main` branch (move to `tools/`). TS: strict mode, ESLint, no `any` (present in saved-projects state), components ≤300 lines, colocate hooks. Both: conventional commits (current history: "brace", "BOM", "Length" — too terse), PR template requiring eval-harness run for extraction changes. Secrets: remove committed `.env`, rotate keys, add `.gitignore` entries for logs/outputs/`.next`.

## 11. Refactoring Priorities

1. Split `main.py` (routers/extraction/services) — prerequisite for everything.
2. Unify persistence on Supabase; delete JSON save path; wire auth into takeoff UI (`apiFetch` already exists).
3. Decompose `page.tsx`; env-based API URL.
4. File storage → R2 with signed URLs; sanitize filenames (security fix).
5. Async jobs for `/analyse`/`/model`.
6. Restore/rewrite 3D viewer and project routes; commit them (avoid repeat of the code-loss incident — enforce push-before-cleanup and CI).

## 12. Implementation Roadmap (by business value) **[Rec]**

| Phase | ~Weeks | Deliverable |
|---|---|---|
| 1. Stabilize | 2–3 | Repo hygiene, secrets rotation, backend split, auth wired, Supabase persistence, CI (lint+eval harness) |
| 2. Project workflow | 3–4 | Projects home, workspace route, per-page state in DB, R2 storage, async analyse with progress |
| 3. BOM v1 | 3 | Section-property DB (AISC shapes), weights/lengths, BOM grid, CSV/KISS export |
| 4. 3D viewer | 2 | Three.js viewer on `/model`, member-type coloring |
| 5. Engineering config & build | 6–8 | Config module (design method, connection defaults, materials), piecemarking, connection material in BOM |
| 6. Schedulers & exports | 4–6 | Column groups/splices, braced frames, Tekla EPM/IFC/marked-up PDF |
| 7. Collaboration | 4 | Sharing, roles, activity log, notifications |

## 13. Testing Strategy **[Rec]**

Promote `eval_harness.py` to CI gate (fail on baseline regression); convert `test_*.py`/`_integration_test.py` ad-hoc scripts to pytest with fixtures; add API tests (auth, RLS, upload validation); frontend: Playwright E2E (upload→analyse→correct→save→BOM), component tests for canvas math; ground-truth corpus expansion per `eval_groundtruth.json` hook already present.

## 14. Deployment Recommendations **[Rec]**

Dockerize backend (python:3.12-slim + PyMuPDF/OpenCV) and frontend; deploy backend on a container host (Fly/Railway/ECS) with a worker process; frontend on Vercel; Supabase managed (DB/auth), Cloudflare R2 for files; GitHub Actions: lint → tests → eval harness → build → deploy staging → manual prod promote; Sentry + structured logs (replace committed `*.log` files).

## 15. Development Plan Summary

The extraction engine is the crown jewel — mature, measured, and regression-protected. The product shell around it is half-built and split-brained (unauth'd local-file app vs. unused Supabase app), and the 3D viewer/project pages were lost. The fastest path to a usable internal product: **stabilize and unify (Phases 1–2), ship BOM v1 and the restored 3D viewer (Phases 3–4)** — that yields an end-to-end takeoff tool in ~10–12 weeks — then invest in the engineering/connection layer (Phases 5–6) to approach target-product parity.
