# SPDX-License-Identifier: Apache-2.0
"""A run's timeline and report (build spec, "Timeline and report").

Pure logic over a run directory: no engine and no network. `timeline` reads and filters the
events, `summary` turns each into one line, and `report` writes the self-contained HTML page.
"""
