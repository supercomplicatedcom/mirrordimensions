# SPDX-License-Identifier: Apache-2.0
"""Doctor reports each design goal on its own (decision 0027)."""

from __future__ import annotations

from mirrordimensions.network.egress_check import Check, report_from


def _checks(**fail: bool) -> list[Check]:
    suites = ("egress", "separation", "inside-out", "naming", "transparency", "capture")
    return [
        Check(
            suite=s, name=f"{s} check", outcome="fail" if fail.get(s.replace("-", "_")) else "pass"
        )
        for s in suites
    ]


def test_all_pass() -> None:
    report = report_from(_checks(), "lima", "dedicated-vm")
    assert (report.isolation, report.coverage, report.undetectability) == (
        "full",
        "complete",
        "full",
    )
    assert report.all_held


def test_a_slow_gateway_is_not_a_broken_seal() -> None:
    report = report_from(_checks(transparency=True), "lima", "dedicated-vm")
    assert report.isolation == "full"
    assert report.undetectability == "failed"
    assert not report.all_held
    assert [c.suite for c in report.failed_in(frozenset({"transparency"}))] == ["transparency"]


def test_each_goal_fails_on_its_own_checks() -> None:
    assert report_from(_checks(egress=True), "lima", "x").isolation == "failed"
    assert report_from(_checks(inside_out=True), "lima", "x").isolation == "failed"
    assert report_from(_checks(capture=True), "lima", "x").coverage == "incomplete"
    assert report_from(_checks(naming=True), "lima", "x").undetectability == "failed"
    assert report_from(_checks(naming=True), "lima", "x").isolation == "full"


def test_a_weaker_boundary_is_reduced() -> None:
    assert report_from(_checks(), "docker", "shared-kernel").isolation == "reduced"
