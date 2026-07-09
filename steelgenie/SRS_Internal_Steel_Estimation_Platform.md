# Software Requirements Specification & Product Design Document
## Internal Structural Steel Estimation Platform (working name: "CalSteel Estimator")

**Version:** 1.0 · **Date:** 2026-07-07 · **Author:** Solution Architecture / Product
**Basis:** Feature-level, black-box analysis of an observed reference application (SteelGenie by Allplan, app v1.5.1) using an authorized evaluation account. All conclusions are drawn from observable UI behavior only. Anything not directly observed is explicitly labeled **[Assumption]** or **[Recommendation]**. No proprietary code, algorithms, or internal data of the reference product were accessed or reproduced.

---

## 1. Purpose & Scope

Build an internal web application that lets steel fabrication estimators upload structural drawing PDFs, detect/mark up structural members, automatically design connections, and produce priced/exportable Bills of Materials (BOM), quantity takeoffs, and 3D model outputs compatible with fabrication-management tools (e.g., Tekla PowerFab / KISS).

**Observed product positioning:** "Structural Steel Estimating Platform" — AI-assisted plan parsing + member detection + connection design + BOM generation + 3D model + fabrication exports.

---

## 2. Complete User Journey (observed)

1. **Sign in** → lands on **Projects** home.
2. **Create project**: "Add New Project" → modal with two modes: **Upload File** (PDF, max 500 MB) or **Blank Project**. Fields: Name (required), Project Number, Status (default "In Progress"), Design Standard (AISC – United States), Unit System (Imperial ft-in; dropdown implies Metric option), Location, Description, and an opt-in checkbox allowing vendor access for quality improvement.
3. **Automated document analysis**: after upload, an AI pipeline ("Genie is analyzing the document…") scans sheets, classifies pages (e.g., "Level 2 Framing Plan", sheet numbers S-112A, S104), extracts scale, and infers project-level engineering settings (e.g., detects "ASD" and the seismic force-resisting system from sheet notes, with an explanatory "Genie Insights" rationale in Config).
4. **Plans workspace (per page)**: user validates page metadata — Top of Steel (T.O.S.) elevation, drawing Scale (with a scale-calibration tool), page Status (Not Started → Estimating → …). User reviews/edits detected members (beams, columns, braces) on the drawing overlay, draws missing members, annotates, measures.
5. **Build**: per page, user triggers **Build** (or **Clean** to discard). Page shows "Requesting Build" while queued; leaving with pending builds prompts "Pending build pages — are you sure you want to leave?". Build runs member analysis + connection design server-side. Columns/Braces/BOM/3D tabs are disabled with tooltip "Build the project first" until at least one build completes.
6. **Config**: user reviews/overrides AI-selected engineering configuration (design method, reactions, seismic frame, connection types, materials, size priorities, labor codes) and clicks **Apply** (or **Reset All**).
7. **Columns (Column Scheduler)**: review auto-grouped column schedules (elevation diagrams per group with splice levels, base plate, anchors, member lists, grids), adjust and Apply.
8. **Braces (Braced Frame)**: define/review braced-frame elevations ("Click to add braced frame"), searchable brace list, Apply.
9. **BOM**: filterable/sortable bill of materials table; configure visible **Fields**; **Export** to Tekla EPM Excel, Bill of Material, or KISS file.
10. **3D**: split-pane 3D viewer of the built model with display modes (Building / Member Type coloring, legend), selection tools.
11. **Export/share**: top-bar actions — **PDF** (marked-up plan PDF), **Export as PDF**, **Export as IFC**, **Open in Bluebeam** (requires connecting an account); project card actions — Update, Share, Move (to folder), Clone, Delete, Pin.
12. **Company administration** (Manager role): manage members, invitations, licenses, activity log, tickets, company-level labor codes.

---

## 3. Functional Modules (observed)

| # | Module | Summary |
|---|--------|---------|
| 1 | Authentication & Account | Login, profile, password change, MFA (authenticator app), license status (Trial, valid-until date) |
| 2 | Projects Home | My Projects / Company Projects / Examples tabs, folders, search, sort, grid/table views, project CRUD (Update/Share/Move/Clone/Delete/Pin), status badge |
| 3 | Project Creation & Ingestion | PDF upload (≤500 MB) or blank project; metadata; AI document analysis |
| 4 | Plans Workspace (Blueprint Editor) | Page list w/ thumbnails, T.O.S., scale + calibration, page status; drawing canvas with layer filter, color-by, fit-to-view, detection region, reference points, key plan, roof-slope regions, abbreviations toggle, member tools (Column "C", Structural Members, Text "T", Annotate, Measure "M"), history panel, undo/redo, properties panel |
| 5 | Member Management | Members panel per page (Columns n, Beams n, Braces), search, multi-select, bulk property edit (rotation, member type, section size, status e.g. "Need Review"), linear copy, delete; per-member Summary/Member/Column property tabs |
| 6 | Build Engine | Per-page Build / Clean; queued builds; gates Columns/Braces/BOM/3D until built |
| 7 | Configuration (estimation rules) | See §8 below — connection design method, beam end reactions, seismic frames, connection types, materials, size priorities, labor codes; AI-suggested defaults with "Genie Insights" rationale |
| 8 | Column Scheduler | Auto column groups, elevation diagrams, splice/base plate/anchor data, per-group member & grid lists, scale, validation warnings |
| 9 | Braced Frame Scheduler | Braced-frame elevation creation/editing, brace search |
| 10 | BOM / Library | Tabular BOM with rich filters, field chooser, exports |
| 11 | 3D Viewer | Model view, color-by Building/Member Type, legend, selection box tools |
| 12 | Exports & Integrations | PDF, IFC, Tekla EPM Excel, KISS, Bluebeam connection |
| 13 | Company Admin ("My Company") | Overview KPIs (projects, members, licenses, invitations), member projects, member/role management, invitations, license assignment, activity log, support tickets, labor-code catalog |
| 14 | Settings | Profile, security (password, MFA), My Tickets |
| 15 | Help & Feedback | Support menu: give feedback per project, view tickets, help center, product roadmap, release notes, app version |
| 16 | Notifications | Bell panel with product announcements (release notes, tutorials); items link out |

---

## 4. Navigation Hierarchy (observed)

```
/ (app shell: logo, home, notifications, help, avatar)
├── /projects (home)
│   ├── Tabs: My Projects | Company Projects | Examples
│   ├── Folders (New Folder), Search, Sort (Latest modified), Grid/Table toggle
│   └── /projects/:id  (project workspace; top tabs)
│       ├── Plans (default)         — left nav: Pages | Members
│       ├── /column-scheduler       — "Columns"
│       ├── /brace-scheduler        — "Braces"
│       ├── /bom                    — "BOM"
│       └── /configurations        — "Config" (left nav anchors per section)
│       └── Top-right: PDF | 3D (toggle pane) | Export (PDF/IFC/Bluebeam) | bell | help | avatar
├── /my-company/{overview|projects|members|invitations|licenses|activities|tickets|labor-codes}
└── /settings/{profile|tickets}
```

---

## 5. User Roles & Permissions (observable)

- **Manager** — access to My Company admin (members, invitations, licenses, labor codes, activities, tickets); full project rights.
- **Member** — standard user; **[Assumption]** limited to own/shared projects, no company admin.
- **License states**: Active / No license; license types (Trial observed) with validity dates; company owns a license pool ("5 licenses, 3 assigned").
- Project sharing exists (Share action; Company Projects tab implies org-visible projects).

**[Recommendation]** for the new build: roles Admin, Manager, Estimator, Viewer; project-level ACL (owner/editor/viewer); license/seat management optional for an internal tool.

---

## 6. Project Lifecycle (observed)

`Created (Upload/Blank)` → `AI Analysis` → `Page validation (T.O.S., scale, status per page: Not Started → Estimating → …)` → `Member detection/markup` → `Build (per page; Requesting Build → Built)` → `Config refinement → re-Build` → `Schedulers (Columns/Braces)` → `BOM/3D` → `Exports`.
Project-level status field: "In Progress" (dropdown at creation implies other states, e.g. completed/on hold — **[Assumption]**). Projects can be pinned, cloned, moved to folders, shared, deleted.

---

## 7. Drawing / Document Management Workflow (observed)

- One PDF binder per project (multi-sheet). Pages auto-split; each page card shows thumbnail, detected title ("Level 2 Framing Plan"), sheet number ("Sheet S-112A"), play (process) button and kebab menu.
- Per-page metadata: **Top of Steel** (validated input: "set a valid T.O.S."), **Scale** (preset list e.g. 1/8"=1'-0", 3/16"=1'-0", plus interactive scale calibration on the drawing), **Status**.
- Canvas overlay renders detected members color-coded (beams red, columns green nodes, braces blue tags) on top of the original plan; layer filter and "Color By" control the display; Key Plan and Detection Region tools bound the parse area; Reference Points align sheets; Roof Slope Regions capture sloped framing; abbreviation legend toggle.
- Full undo/redo + history panel of edits.

---

## 8. Estimation Workflow & Configuration (observed)

The Config module drives connection design/estimation. AI pre-selects values and displays rationale ("Genie Insights"). Sections:

1. **Connection Design Method**: ASD (default) / LRFD.
2. **Beam End Reaction Calculation**: gathering mode — Use plan reactions + auto-calculate missing (default) / Ignore plan reactions / Plan reactions only; method — Maximum Web Shear (under development) / UDL (default) with adjustable **UDL percentage** (20–100%, default 50%).
3. **Seismic Frame Type**: Moment frame — Non-Seismic (default), OMF/IMF/SMF (under development); Brace frame — Non-Seismic (beta), OCBF/SCBF (beta), BRB (under development).
4. **Connection Types**: Beam–Column (simple: Bolted Double Angle default / Shear Tab; moment: Shear Tab), Beam–Girder, Column Splice (auto-splicing toggle, max section height before splice, method: bolted flange w/ inner plate, bolted flange, welded flange (default), bolted body), Vertical/Horizontal Brace (welded/bolted), Base Plate (welded). Options: full-depth welded shear tab, welded clip angle, force maximum connection, maximize plate & bolts.
5. **Material Settings**: default grade per shape family (W/WT=A992, S/ST/C/L/M/MT/MC=A36, HP=A572 Gr.50, HSS Rect/Round=A500 Gr.C, Pipe=A53 Gr.B, Anchor=Gr.36, Weld Stud=A108, Plate=A50, Bolt=F3125 A325-N, Electrode=E70XX, …).
6. **Size Priorities**: ordered plate-thickness priority for shear tabs and double angles; bolt-diameter priority (3/4, 7/8, 1).
7. **Labor Codes**: project-level mapping of shapes → labor codes for Tekla PowerFab export; routing toggle; member length basis (Face to Face); catalog inherited from company-level labor codes.

Apply / Reset All commits config; re-build reflects changes.

---

## 9. Quantity Takeoff Workflow (observed)

- Detection region + AI parse produce member candidates per page; the estimator corrects/adds members manually (draw column/beam/brace, set section size, rotation).
- Member statuses (e.g., "Need Review") support QA triage; bulk selection + property panel accelerate cleanup.
- Build converts validated 2D members + config into piecemarked assemblies with connection material (plates, bolts, angles), producing the BOM (weights in lbs, lengths ft-in, camber, cope, holes, weld studs counts).

---

## 10. Reporting & Exports (observed)

- **BOM exports**: Tekla EPM Excel, "Export Bill of Material", KISS file (steel-industry standard).
- **Drawing/model exports**: marked-up **PDF**, **IFC** model, **Open in Bluebeam** (account connection required).
- BOM table doubles as the on-screen report: pagination ("Showing 1–2 of 2 items"), column chooser (Fields), full filter panel.
- **[Recommendation]** add priced-estimate report (tonnage × rates + labor hours) and Excel summary by category/sequence.

## 11. Dashboard Functionality (observed)

- Projects home is the de-facto dashboard (cards with status badges, modified time).
- **My Company Overview**: KPI cards — Projects (12), Members (5, with active licenses), Licenses (5, 3 assigned), Invitations (5, 2 pending); company profile w/ address.
- **[Recommendation]** add an estimating dashboard: tonnage pipeline, bid due dates, win rate, per-estimator workload.

## 12. Search & Filtering (observed)

- Projects: text search, sort by latest modified, folder grouping, grid/table.
- Members panel: search members (e.g., "C_1, W10…"), category grouping w/ counts.
- Column/Brace schedulers: search columns/braces; scale selector.
- BOM: text search ("matches visible columns & custom fields") + faceted filters: Category, Piecemark, Section Type, Section, Grade, Labor Code, Main/Accessory, Status, Sequence, Paint.
- Company members: search by name/email; role filter.

## 13. Notifications (observed)

Bell panel with dated product announcements (release notes, tutorials). No observed in-app task notifications (e.g., build-completed toasts were not directly observed but implied by async builds — **[Assumption]**).
**[Recommendation]**: event notifications (build finished/failed, share received, export ready), email digests, per-user preferences.

## 14. Settings (observed)

Profile (name, email, company, role), license status/type/validity, change password, MFA via authenticator app, My Tickets. Company Settings via My Company (company info edit, address).

## 15. Collaboration Features (observed)

Project Share; Company Projects visibility; folders; clone; company member/invitation management; per-project feedback + ticketing to the vendor; opt-in data sharing at project creation.
**[Recommendation]**: real-time co-editing indicators, comments/mentions on pages and members, audit trail per project.

---

## 16. Data Entities (derived from observed behavior)

Company, User, Membership(role), Invitation, License, ActivityLog, Ticket, Folder, Project, ProjectShare, Document(PDF), Page(sheet no, title, scale, TOS, status), DetectionRegion, ReferencePoint, RoofSlopeRegion, Annotation, Measurement, Member(type: beam/column/brace; section, grade, rotation, geometry, status), ColumnGroup, ColumnLevel/Splice, BasePlate, AnchorSet, BracedFrame, Brace, BuildJob, Configuration(project settings incl. all §8 sections), MaterialGradeDefault, SizePriority, LaborCode(company + project override), BOMItem(piecemark, qty, section, length, grade, labor code, weight, camber, cope, holes, weld studs, status, sequence, paint, main/accessory), ExportJob, Notification, GenieInsight(AI rationale text tied to config), Model3D artifacts.

## 17. Suggested Database Design **[Recommendation]**

PostgreSQL; multi-tenant by `company_id`. Key tables (abridged):

```
companies(id, name, email, address, created_at)
users(id, company_id, name, email, password_hash, mfa_secret, role ENUM(admin,manager,member), created_at)
licenses(id, company_id, type, status, valid_until, assigned_user_id)
invitations(id, company_id, email, role, status, invited_by, created_at)
folders(id, company_id, name, owner_id)
projects(id, company_id, owner_id, folder_id, name, number, status, design_standard,
         unit_system, location, description, is_pinned, share_scope, created_at, updated_at)
project_shares(project_id, user_id, permission)
documents(id, project_id, s3_key, size_bytes, page_count, analysis_status)
pages(id, document_id, index, sheet_no, title, scale, top_of_steel, status, thumbnail_key)
members(id, page_id, type, section, grade, rotation, status, geometry JSONB, piecemark, source ENUM(ai,manual))
annotations(id, page_id, kind, payload JSONB, author_id)
configurations(project_id PK, payload JSONB, ai_insights JSONB, applied_at)   -- versioned via config_revisions
column_groups(id, project_id, name, columns int[], splice JSONB, base_plate JSONB, anchors JSONB, warnings JSONB)
braced_frames(id, project_id, name, geometry JSONB)
build_jobs(id, project_id, page_id, status ENUM(queued,running,succeeded,failed), started_at, finished_at, error)
bom_items(id, project_id, build_id, piecemark, category, qty, section_type, section, length_in, grade,
          labor_code, weight_lbs, camber, cope, holes, weld_studs, status, sequence, paint, is_main, custom JSONB)
labor_codes(id, company_id, code, description, category, shape_pattern)
activity_logs(id, company_id, user_id, action, entity, entity_id, ts)
tickets(id, company_id, user_id, project_id, subject, body, status)
notifications(id, user_id, type, title, body, read_at, ts)
export_jobs(id, project_id, format ENUM(pdf,ifc,epm_xlsx,kiss,bom_xlsx), status, file_key)
```
Geometry/model artifacts (IFC, glTF for 3D viewer, page raster tiles) in object storage; page vectors optionally in JSONB.

## 18. Suggested REST API **[Recommendation]**

```
POST /auth/login | /auth/mfa/verify | POST /auth/password
GET/POST /companies/:id/members|invitations|licenses|activities|labor-codes
GET/POST /folders ; GET/POST /projects ; GET/PATCH/DELETE /projects/:id
POST /projects/:id/clone|share|move|pin
POST /projects/:id/documents (multipart)          → triggers analysis
GET  /projects/:id/pages ; PATCH /pages/:id       (tos, scale, status)
GET/POST/PATCH/DELETE /pages/:id/members  (+ /bulk)
POST /pages/:id/build ; POST /pages/:id/clean ; GET /projects/:id/builds/:jobId
GET/PUT /projects/:id/configuration ; POST /projects/:id/configuration/reset
GET/PATCH /projects/:id/column-groups ; GET/POST /projects/:id/braced-frames
GET /projects/:id/bom?filters…&fields… ; POST /projects/:id/exports {format}
GET /exports/:id (status/download URL)
GET /projects/:id/model (glTF/IFC ref)
GET/PATCH /me ; GET /notifications ; POST /tickets
WS  /ws (build progress, analysis progress, notifications)
```

## 19. Frontend Component Hierarchy **[Recommendation]**

```
AppShell (TopBar: ProjectTabs, ExportMenu, NotificationsPopover, HelpMenu, AvatarMenu)
├─ ProjectsHome (Tabs, SearchBar, FolderBar, ViewToggle, ProjectCard/Table, CreateProjectModal)
├─ ProjectWorkspace
│  ├─ PlansView
│  │  ├─ LeftPanel (PagesList[PageCard: Thumbnail, TOSInput, ScaleSelect+Calibrate, StatusSelect]
│  │  │            | MembersPanel [BuildBar(Clean/Build), MemberSearch, CategoryGroups])
│  │  ├─ CanvasToolbar (LayerFilter, ColorBy, Fit, DetectionRegion, RefPoints, KeyPlan,
│  │  │                 RoofSlope, Abbrev, ColumnTool, MemberTool, TextTool, Annotate,
│  │  │                 Measure, History, Undo/Redo)
│  │  ├─ PlanCanvas (WebGL/canvas: PDF raster tiles + member overlay + selection)
│  │  └─ PropertiesPanel (Summary/Member/Column tabs, BulkEditor, DeleteBar)
│  ├─ ColumnSchedulerView (GroupList, ElevationDiagram, GroupDetailCards, Apply/Reset)
│  ├─ BracedFrameView (FrameCards, AddFrame, Apply/Reset)
│  ├─ BOMView (FilterSidebar, FieldsChooser, ExportMenu, DataGrid, Pagination)
│  ├─ Viewer3D (dockable split pane; ColorMode, Legend, SelectTools)
│  └─ ConfigView (SectionNav, ConfigSections ×7, GenieInsightsBanner, Apply/ResetAll)
├─ MyCompany (Overview, Projects, Members, Invitations, Licenses, Activities, Tickets, LaborCodes)
└─ Settings (Profile, MyTickets)
```

## 20. Backend Service Decomposition **[Recommendation]**

- **API Gateway / BFF** (auth, tenancy, REST+WS)
- **Identity & Org service** (users, roles, licenses, invitations, MFA)
- **Project service** (projects, folders, sharing, config)
- **Document Ingestion service** (upload, PDF split, rasterize/tile, thumbnails)
- **AI Analysis service** (page classification, scale/T.O.S. extraction, member detection, config inference w/ rationale) — GPU workers, queue-driven
- **Build/Engineering service** (member graph → connection design per config → piecemarks, BOM, 3D model, column/brace schedules) — CPU workers, queue-driven
- **Export service** (PDF/IFC/EPM-Excel/KISS generation)
- **Notification service** (WS + email)
- **Support/feedback service** (tickets)
- Shared: PostgreSQL, Redis (queues/cache), object storage, message broker (SQS/RabbitMQ).

## 21. Cloud Architecture **[Recommendation]**

SPA (CDN) → ALB → containerized services (EKS/ECS); Postgres (RDS Multi-AZ), Redis (ElastiCache), S3 + CloudFront for tiles/artifacts, SQS for analysis/build/export queues, GPU node pool for ML inference, WebSocket via API Gateway/ALB sticky, Secrets Manager, CloudWatch/OpenTelemetry. Single-tenant internal deployment can collapse to one VPC, two AZs.

## 22. Recommended Technology Stack **[Recommendation]**

Frontend: React + TypeScript, Vite, Zustand/Redux, TanStack Table/Query, deck.gl or custom WebGL canvas for plan overlay, Three.js for 3D, pdf.js + server-side tiling. Backend: Node (NestJS) or Python (FastAPI) for APIs; Python for ML (PyTorch, layout/detection models) and engineering engine (steel section DB, AISC checks); worker orchestration with Celery/BullMQ. Formats: IFC via IfcOpenShell; KISS/EPM writers custom. Auth: OIDC (company SSO) + TOTP MFA.

## 23. Performance Considerations **[Recommendation]**

Tile large PDF sheets (deep-zoom) rather than full-page rendering; virtualize member lists and BOM grid; debounce canvas edits with optimistic UI + undo stack client-side; run analysis/builds async with progress events (observed builds are queued and pages remain usable); cache section-property lookups; paginate/lazy-load thumbnails; target <2 s interactive plan pan/zoom on 5,000-member sheets.

## 24. Security Best Practices **[Recommendation]**

Tenant isolation on every query; RBAC (role + project ACL); signed, expiring URLs for file access; virus/type scan on upload; MFA + SSO; audit log (mirrors observed Activities); encrypt at rest/in transit; rate limiting; no drawing data leaves tenant boundary unless an explicit opt-in flag is set (mirror observed consent checkbox); secrets in vault; dependency and container scanning.

## 25. Scalability Considerations **[Recommendation]**

Stateless API scale-out; queue-based GPU/CPU worker autoscaling on backlog; per-page build granularity (observed) parallelizes naturally; object storage for all heavy artifacts; read replicas for BOM/reporting; partition BOM/members by project_id; idempotent build jobs with versioned outputs so re-builds don't corrupt exports.

## 26. Testing Strategy **[Recommendation]**

- Unit: engineering engine (connection capacity tables, reaction calcs, splice logic) with golden-value fixtures from AISC examples.
- ML evaluation: labeled sheet corpus; precision/recall per member class; regression gates before model rollout.
- Integration: upload→analyze→build→BOM pipeline against sample binders; export file validators (KISS/EPM schema, IFC syntax).
- E2E: Playwright flows for the journey in §2; visual regression on canvas overlays.
- Performance: large-binder load tests; concurrency on build queue.
- UAT with estimators comparing outputs to a manually estimated benchmark job (tonnage within agreed tolerance).

## 27. Deployment Strategy **[Recommendation]**

Trunk-based dev; CI (lint, tests, container build, SBOM); environments dev→staging→prod; blue/green or rolling deploys; DB migrations gated (expand/contract); model registry with canary rollout for ML models; feature flags for "Under Development" features (the reference product visibly ships flagged beta/under-development options — a pattern worth copying).

## 28. Development Roadmap & Phase Plan **[Recommendation]**

| Phase | Duration (indicative) | Scope |
|---|---|---|
| 0 – Foundations | 4–6 wks | Auth/SSO, tenancy, projects home, PDF upload/split/tiling, page viewer |
| 1 – Manual Takeoff MVP | 8–10 wks | Member drawing tools, properties/bulk edit, scale calibration, T.O.S., statuses, undo/redo, basic BOM (weights from section DB), Excel export |
| 2 – Engineering Build | 10–12 wks | Config module (ASD/LRFD, reactions/UDL, connection types, materials, size priorities), build engine, piecemarks, connection material in BOM, KISS/EPM exports |
| 3 – Schedulers & 3D | 8 wks | Column scheduler (groups, splices, base plates, anchors), braced frames, 3D viewer, IFC/PDF export |
| 4 – AI Assist | 10–14 wks | Page classification, member detection, scale/T.O.S. extraction, config inference with rationale (explainability like "Genie Insights") |
| 5 – Collaboration & Admin | 6 wks | Sharing, folders, company admin, activity log, labor-code catalogs, notifications, ticketsing |
| 6 – Hardening | ongoing | Performance, model retraining loop, pricing/reporting add-ons |

Phases 1–2 already deliver value without AI; AI is an accelerator, not a dependency.

## 29. Improvement Opportunities over the Observed Product

1. **Pricing layer**: observed product stops at quantities/labor codes; add rate tables → priced estimates and bid letters.
2. **Build feedback**: clearer progress/ETA and failure diagnostics (observed only "Requesting Build" badge and a leave-warning dialog).
3. **Project-level build**: batch "build all pages" with dependency awareness.
4. **In-app collaboration**: comments, mentions, review assignments per member/page (observed has statuses only).
5. **Version compare**: diff BOM between builds/addenda revisions of drawings.
6. **Better empty/gated states**: disabled tabs say "Build the project first" — deep-link the user to the exact next action.
7. **Bulk QA views**: table of all members across pages filtered by "Need Review".
8. **Offline-tolerant canvas** and autosave indicators.
9. **Metric-first support** and localized section databases (observed defaults are US/AISC-centric).
10. **Notification usefulness**: observed bell only carries vendor announcements; add job/event notifications.
11. **Performance**: several page loads took >5 s and screenshots timed out during heavy renders in evaluation; tiled rendering + skeleton states should target faster first paint.
12. **Search everywhere**: global search across projects/pages/piecemarks.

---

### Appendix A — Observed value lists
- Page scales: 1/8"=1'-0", 3/16"=1'-0" (preset dropdown + calibration).
- Member statuses: Not Started, Need Review, Estimating (page), In Progress (project).
- BOM columns: Main, Category, Piecemark, Qty, Section Type, Section, Length, Grade, Labor Code, Weight-lbs, Camber, Cope, Hole, Weld Stud, Status, Sequence (+ Fields chooser, custom fields implied by search hint).
- Labor code categories: Beams, Columns, Vertical Braces, Horizontal Braces, Field Materials.
- Export formats: Tekla EPM Excel, BOM, KISS, PDF, IFC, Bluebeam link.
- Help menu: feedback, my tickets, help center, product roadmap, release notes, version.

*End of document.*
