# SPDX-License-Identifier: Apache-2.0
FROM python:3.13-alpine@sha256:9ef1a599f863231c3d91e941389bfdc4a2d6070557243d54df1a4e57015b960e
RUN adduser -D -u 1000 svc
COPY agent.py /opt/triage/agent.py
USER svc
WORKDIR /home/svc
CMD ["python", "/opt/triage/agent.py"]
