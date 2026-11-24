# SPDX-FileCopyrightText: 2026 Supercomplicated LLC
# SPDX-License-Identifier: Apache-2.0
FROM python:3.13-slim
# Playwright's client runs a bundled Node driver, which needs libatomic. No browser is
# installed here: the agent drives the company's managed browser over DevTools.
RUN apt-get update && apt-get install -y --no-install-recommends libatomic1 \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir playwright==1.65.2
COPY agent.py /opt/desk/agent.py
RUN useradd --create-home desk
USER desk
