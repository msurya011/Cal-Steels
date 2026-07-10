"""
Engineering (build) engine — original implementation from public AISC references.

Converts validated 2D members + project configuration into piecemarked
assemblies (main + accessory BOM rows), column groups, and braced frames.

No proprietary algorithms or data from any third-party product are used here;
capacity tables are simplified, published AISC-style allowable/available
values intended for a deterministic MVP engine (see connections.py for the
explicit accuracy caveat). Engine is versioned so BOM output is reproducible
and diffable across runs.
"""
from __future__ import annotations

ENGINE_VERSION = "0.1.0-mvp"
