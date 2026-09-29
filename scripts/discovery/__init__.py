# -*- coding: utf-8 -*-
"""Magazine discovery: source registry -> adapters -> candidate store -> normalize -> dedup ->
quality -> classify -> rank -> editorial selection -> public snapshot (docs/MAGAZINE_DISCOVERY.md).

Babdoduk owns these adapters and the data model. Agent Reach is only a capability reference
(and an optional local doctor): nothing here imports it, and nothing here can publish text
that the source itself does not contain.
"""
