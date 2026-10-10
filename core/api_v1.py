#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
core/api_v1.py
==============
Машинний REST API v1 для інтеграції DIMS з ІАС (специфікація —
docs/openapi_v1.yaml, опис — docs/ias_integration_ua.md).

Автентифікація: сервісні токени з DIMS_SERVICE_TOKENS (через кому),
передаються як «Authorization: Bearer <token>». Якщо токени не налаштовано,
API повертає 503 — сервіс не можна випадково відкрити без захисту.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os

from flask import Blueprint, current_app, jsonify, request

from core.ias_service import GRADES, AssessmentError, assess_event
from core.ias_store import ALERT_STATUSES, IasStore

bp = Blueprint("api_v1", __name__, url_prefix="/api/v1")

_STORE: IasStore | None = None


def get_store() -> IasStore:
    global _STORE
    if _STORE is None:
        _STORE = IasStore()
    return _STORE


def _error(message: str, code: int):
    return jsonify({"ok": False, "error": message}), code


def _service_tokens() -> list[str]:
    raw = os.environ.get("DIMS_SERVICE_TOKENS", "")
    return [t.strip() for t in raw.split(",") if t.strip()]


def _client_id(token: str) -> str:
    """Необоротний короткий ідентифікатор клієнта для журналів (не сам токен)."""
    return "svc-" + hashlib.sha256(token.encode()).hexdigest()[:8]


@bp.before_request
def _authenticate():
    tokens = _service_tokens()
    if not tokens:
        return _error("API v1 не налаштовано: задайте DIMS_SERVICE_TOKENS.", 503)
    header = request.headers.get("Authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    if not supplied or not any(hmac.compare_digest(supplied, t) for t in tokens):
        return _error("Потрібен дійсний сервісний токен (Authorization: Bearer).", 401)
    request.environ["dims.client"] = _client_id(supplied)
    return None


# ── Оцінка події ────────────────────────────────────────────────────────────

@bp.post("/assess")
def assess():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return _error("Очікується JSON-об'єкт.", 400)
    params = data.get("params") or {}
    if not isinstance(params, dict):
        return _error("params має бути об'єктом.", 400)
    try:
        result = assess_event(
            data.get("materials"),
            event_id=str(data["event_id"]) if data.get("event_id") is not None else None,
            manifestation=data.get("manifestation"),
            mfw_n=int(params.get("mfw_n", 100)),
            threshold=float(params.get("threshold", 0.8)),
            feature_type=str(params.get("feature_type", "word")).lower(),
            with_confidence=params.get("confidence", True) not in (False, "false", 0, "0"),
        )
    except AssessmentError as exc:
        return _error(str(exc), 422)
    except (TypeError, ValueError):
        return _error("Некоректні параметри оцінки.", 400)
    current_app.logger.info("api_v1 assess client=%s event=%s grade=%s r=%.3f",
                            request.environ.get("dims.client"), result["event_id"],
                            result["grade"]["grade"], result["r_dims"])
    return jsonify({"ok": True, "assessment": result})


@bp.get("/events/<event_id>/assessment")
def event_assessment(event_id: str):
    result = get_store().get_assessment(event_id)
    if result is None:
        return _error("Подію ще не оцінено.", 404)
    return jsonify({"ok": True, "assessment": result})


# ── Сповіщення ──────────────────────────────────────────────────────────────

@bp.get("/alerts")
def list_alerts():
    status = request.args.get("status") or None
    if status and status not in ALERT_STATUSES:
        return _error("status має бути одним із: " + ", ".join(sorted(ALERT_STATUSES)), 400)
    try:
        since_id = max(0, int(request.args.get("since_id", 0)))
        limit = min(200, max(1, int(request.args.get("limit", 50))))
    except ValueError:
        return _error("since_id і limit мають бути цілими числами.", 400)
    return jsonify({"ok": True, "alerts": get_store().list_alerts(status, since_id, limit)})


@bp.get("/alerts/<int:alert_id>")
def get_alert(alert_id: int):
    alert = get_store().get_alert(alert_id)
    if alert is None:
        return _error("Сповіщення не знайдено.", 404)
    return jsonify({"ok": True, "alert": alert})


@bp.post("/alerts/<int:alert_id>/review")
def review_alert(alert_id: int):
    """Рішення аналітика: підтвердити / відхилити + експертний грейд.

    Експертний грейд накопичує пари «DIMS ↔ експерт» для валідації методики."""
    data = request.get_json(silent=True) or {}
    status = str(data.get("status", "")).strip().lower()
    if status not in {"confirmed", "rejected"}:
        return _error("status має бути 'confirmed' або 'rejected'.", 400)
    expert_grade = data.get("expert_grade")
    if expert_grade is not None:
        expert_grade = str(expert_grade).strip().upper()
        if expert_grade not in GRADES:
            return _error("expert_grade має бути одним із: " + ", ".join(GRADES), 400)
    comment = data.get("comment")
    comment = str(comment)[:2000] if comment is not None else None
    reviewer = data.get("reviewer")
    reviewer = str(reviewer)[:200] if reviewer is not None else request.environ.get("dims.client")
    alert = get_store().review_alert(alert_id, status, expert_grade, comment, reviewer)
    if alert is None:
        return _error("Сповіщення не знайдено.", 404)
    return jsonify({"ok": True, "alert": alert})


@bp.get("/feedback")
def feedback():
    return jsonify({"ok": True, "feedback": get_store().feedback()})


# ── Стан сервісу ────────────────────────────────────────────────────────────

@bp.get("/status")
def status():
    store = get_store()
    return jsonify({
        "ok": True,
        "scanner": {
            "watermark": store.get_state("watermark"),
            "last_run_at": store.get_state("last_run_at"),
            "last_run_stats": json.loads(store.get_state("last_run_stats") or "null"),
        },
        "counts": store.counts(),
    })
