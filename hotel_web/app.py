import io
import os
import re
import subprocess
from datetime import datetime
from functools import wraps

import openpyxl
from flask import Flask, jsonify, render_template, request, send_file, session
from flask_cors import CORS
from flask_session import Session

import business as biz
from db_connection import close_db

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "dev-secret-key-change-me")
app.config["SESSION_TYPE"] = "filesystem"
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("SESSION_COOKIE_SECURE", "0") == "1" or os.getenv("FLASK_ENV") == "production"
app.config["SESSION_PERMANENT"] = False
Session(app)
CORS(app, supports_credentials=True)
app.teardown_appcontext(close_db)

ROLES = {"manager", "receptionist", "frontdesk", "customer"}
PHONE_RE = re.compile(r"^\d{11}$")
LOGIN_WINDOW_SECONDS = 10 * 60
LOGIN_LOCK_SECONDS = 15 * 60
LOGIN_MAX_ATTEMPTS = 5
_LOGIN_ATTEMPTS = {}


def _json_unauthorized():
    return jsonify({"error": "未登录"}), 401


def _json_forbidden():
    return jsonify({"error": "权限不足"}), 403


def _json_bad_request(message):
    return jsonify({"success": False, "message": message}), 400


def _is_logged_in():
    return "user" in session


def _current_user():
    return session.get("user")


def _current_role():
    return session.get("role")


def _customer_session_identity():
    cid = session.get("customer_id")
    name = (session.get("customer_name") or session.get("user") or "").strip()
    phone = _validate_phone(session.get("customer_phone"))
    return cid, name, phone


def _require_role(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if not _is_logged_in():
                return _json_unauthorized()
            if allowed and _current_role() not in allowed:
                return _json_forbidden()
            return fn(*args, **kwargs)
        return wrapper
    return deco


def _json_list(rows, fields, transforms=None):
    transforms = transforms or {}
    out = []
    for row in rows:
        item = {}
        for i, k in enumerate(fields):
            v = row[i]
            if k in transforms:
                v = transforms[k](v)
            item[k] = v
        out.append(item)
    return out


def _excel_response(rows, headers, sheet_name, filename):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for r in rows:
        ws.append(list(r))
    b = io.BytesIO()
    wb.save(b)
    b.seek(0)
    return send_file(b, download_name=filename, as_attachment=True)


def _validate_phone(phone):
    p = (phone or "").replace(" ", "").strip()
    return p if PHONE_RE.match(p) else None


def _now_ts():
    return datetime.now().timestamp()


def _client_ip():
    forwarded = (request.headers.get("X-Forwarded-For") or "").split(",")[0].strip()
    return forwarded or request.remote_addr or "unknown"


def _login_key(scope, value):
    return f"{scope}:{(value or '').strip().lower()}"


def _login_buckets(username):
    ip = _client_ip()
    normalized = (username or "").strip().lower()
    return [
        _login_key("ip", ip),
        _login_key("user", normalized),
        _login_key("pair", f"{ip}|{normalized}"),
    ]


def _login_state(key):
    now = _now_ts()
    state = _LOGIN_ATTEMPTS.get(key)
    if not state:
        state = {"count": 0, "first": now, "locked_until": 0}
        _LOGIN_ATTEMPTS[key] = state
        return state
    if state.get("locked_until", 0) and state["locked_until"] <= now:
        state = {"count": 0, "first": now, "locked_until": 0}
        _LOGIN_ATTEMPTS[key] = state
        return state
    if now - state.get("first", now) > LOGIN_WINDOW_SECONDS and not state.get("locked_until", 0):
        state["count"] = 0
        state["first"] = now
    return state


def _login_locked_until(username):
    now = _now_ts()
    locked_until = 0
    for key in _login_buckets(username):
        state = _login_state(key)
        if state.get("locked_until", 0) > now:
            locked_until = max(locked_until, state["locked_until"])
    return locked_until


def _login_mark_failure(username):
    now = _now_ts()
    locked_until = 0
    for key in _login_buckets(username):
        state = _login_state(key)
        if now - state.get("first", now) > LOGIN_WINDOW_SECONDS and not state.get("locked_until", 0):
            state["count"] = 0
            state["first"] = now
        if state.get("locked_until", 0) > now:
            locked_until = max(locked_until, state["locked_until"])
            continue
        state["count"] = state.get("count", 0) + 1
        state["last_fail"] = now
        if state["count"] >= LOGIN_MAX_ATTEMPTS:
            state["locked_until"] = now + LOGIN_LOCK_SECONDS
            state["count"] = 0
            state["first"] = now
            locked_until = max(locked_until, state["locked_until"])
    return locked_until


def _login_clear_attempts(username):
    for key in _login_buckets(username):
        _LOGIN_ATTEMPTS.pop(key, None)


@app.after_request
def add_security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    # 允许同源页面在工作台 iframe 中加载。
    response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
    response.headers.setdefault("Referrer-Policy", "same-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault(
        "Content-Security-Policy",
        "default-src 'self'; base-uri 'self'; frame-ancestors 'self'; object-src 'none'; "
        "form-action 'self'; connect-src 'self'; img-src 'self' data:; font-src 'self' https://cdn.jsdelivr.net data:; "
        "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net;"
    )
    return response


@app.route("/")
def login_page():
    return render_template("login.html")


@app.route("/dashboard")
@_require_role()
def dashboard():
    if _current_role() == "customer":
        return render_template("customer.html", username=_current_user(), role="customer")
    return render_template("base.html", username=_current_user(), role=_current_role())


@app.route("/<page>")
@_require_role()
def pages(page):
    mapping = {
        "front_office": "front_office.html",
        "room_maint": "room_maint.html",
        "query_report": "query_report.html",
        "statistics": "statistics.html",
        "complaint": "complaint.html",
        "system": "system.html",
    }
    if page not in mapping:
        return _json_bad_request("页面不存在")
    allowed = {
        "manager": {"front_office", "room_maint", "query_report", "statistics", "complaint", "system"},
        "receptionist": {"front_office", "room_maint", "query_report", "statistics", "complaint"},
        "frontdesk": {"front_office", "room_maint", "query_report", "statistics", "complaint"},
        "customer": set(),
    }
    if page not in allowed.get(_current_role(), set()):
        return _json_forbidden()
    return render_template(mapping[page], username=_current_user(), role=_current_role())


@app.route("/api/login", methods=["POST"])
def login():
    d = request.get_json(silent=True) or {}
    username = (d.get("username") or "").strip()
    password = d.get("password") or ""
    if not username or not password:
        return _json_bad_request("用户名和密码不能为空")
    if len(username) > 64 or len(password) > 128:
        return _json_bad_request("登录信息格式不正确")

    locked_until = _login_locked_until(username)
    if locked_until:
        wait_seconds = max(1, int(locked_until - _now_ts()))
        return jsonify({"success": False, "message": f"登录过于频繁，请 {wait_seconds} 秒后再试"}), 429

    row = biz.verify_user(username, password)
    if row:
        role = row[0]
        if role not in ROLES:
            return jsonify({"success": False, "message": "角色未配置"})
        session.clear()
        session["user"] = username
        session["role"] = role
        session.pop("customer_id", None)
        session.pop("customer_name", None)
        session.pop("customer_phone", None)
        _login_clear_attempts(username)
        return jsonify({"success": True, "username": username, "role": role})

    phone = _validate_phone(password)
    if not phone:
        wait_seconds = _login_mark_failure(username)
        if wait_seconds:
            return jsonify({"success": False, "message": f"登录过于频繁，请 {max(1, int(wait_seconds - _now_ts()))} 秒后再试"}), 429
        return jsonify({"success": False, "message": "用户名或密码错误"})

    cid, cname = biz.get_or_create_customer_identity(username, phone)
    session.clear()
    session["user"] = username
    session["role"] = "customer"
    session["customer_id"] = int(cid)
    session["customer_name"] = cname
    session["customer_phone"] = phone
    _login_clear_attempts(username)
    return jsonify({"success": True, "username": username, "role": "customer", "message": "按客户身份登录"})


@app.route("/api/logout", methods=["POST"])
def logout():
    session.clear()
    return jsonify({"success": True})


@app.route("/api/current_user")
def current_user():
    if not _is_logged_in():
        return _json_unauthorized()
    payload = {"username": _current_user(), "role": _current_role()}
    if _current_role() == "customer":
        _, cname, cphone = _customer_session_identity()
        payload["customer_name"] = cname
        payload["customer_phone"] = cphone
    return jsonify(payload)


@app.route("/api/rooms")
@_require_role()
def rooms():
    return jsonify(_json_list(biz.list_all_rooms(), ["room_id", "room_type", "area", "price", "status"], {"price": float}))


@app.route("/api/query/rooms", methods=["POST"])
@_require_role()
def query_rooms():
    d = request.json or {}
    rows = biz.advanced_room_query(
        d.get("room_id"),
        d.get("room_type"),
        d.get("status"),
        d.get("area_min"),
        d.get("area_max"),
        d.get("price_min"),
        d.get("price_max"),
        d.get("checkin_date"),
        d.get("checkout_date"),
        d.get("customer_name"),
        d.get("customer_phone"),
        d.get("checkin_time"),
    )
    return jsonify(
        _json_list(
            rows,
            ["room_id", "room_type", "area", "price", "status", "res_id", "customer", "phone", "checkin_time", "checkout_date", "operator"],
            {
                "price": float,
                "checkin_time": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/reservation", methods=["POST"])
@_require_role("manager", "customer")
def reservation():
    d = request.json or {}
    request_name = (d.get("name") or "").strip()
    request_phone = _validate_phone(d.get("phone"))
    name = request_name
    phone = request_phone
    account_nickname = _current_user()
    customer_cust_id = None
    if _current_role() == "customer":
        session_cid, _, _ = _customer_session_identity()
        customer_cust_id = session_cid
    if not name:
        return _json_bad_request("姓名不能为空")
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.make_reservation(
        name,
        phone,
        d["room_id"],
        d["checkin_date"],
        _current_user(),
        d.get("checkout_date"),
        d.get("checkout_time"),
        account_nickname=account_nickname,
        customer_cust_id=customer_cust_id,
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/reservation/manager", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def reservation_manager():
    d = request.json or {}
    request_name = (d.get("name") or "").strip()
    request_phone = _validate_phone(d.get("phone"))
    name = request_name
    phone = request_phone
    if not name:
        return _json_bad_request("姓名不能为空")
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.make_reservation(
        name,
        phone,
        d["room_id"],
        d["checkin_date"],
        _current_user(),
        d.get("checkout_date"),
        d.get("checkout_time"),
        account_nickname=_current_user(),
        customer_cust_id=d.get("customer_cust_id"),
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/reservation/batch", methods=["POST"])
@_require_role("manager", "customer", "frontdesk")
def reservation_batch():
    d = request.json or {}
    request_name = (d.get("name") or "").strip()
    request_phone = _validate_phone(d.get("phone"))
    name = request_name
    phone = request_phone
    account_nickname = _current_user()
    customer_cust_id = None
    if _current_role() == "customer":
        session_cid, _, _ = _customer_session_identity()
        customer_cust_id = session_cid
    if not name:
        return _json_bad_request("姓名不能为空")
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.make_reservation_by_type(
        name,
        phone,
        d["room_type"],
        d["quantity"],
        d["checkin_date"],
        _current_user(),
        d.get("checkout_date"),
        account_nickname=account_nickname,
        customer_cust_id=customer_cust_id,
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/reservation/cancel", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk", "customer")
def reservation_cancel():
    d = request.json or {}
    ok, msg = biz.cancel_reservation(d["info"], _current_user())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/reservation/cancel_by_res_id", methods=["POST"])
@_require_role("customer")
def reservation_cancel_by_res_id():
    d = request.json or {}
    name = d.get("name", "")
    phone = _validate_phone(d.get("phone"))
    _, session_name, session_phone = _customer_session_identity()
    name = session_name or name
    phone = session_phone or phone
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.cancel_reservation_by_res_id(
        d.get("res_id"),
        name,
        phone,
        _current_user(),
        require_owner=True,
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/checkin", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def checkin():
    d = request.json or {}
    if d.get("type") == "reservation":
        ok, msg = biz.checkin_by_reservation_id(d.get("res_id"), _current_user())
    elif d.get("type") == "direct":
        phone = _validate_phone(d.get("phone"))
        if not phone:
            return _json_bad_request("手机号必须为11位数字")
        ok, msg = biz.direct_checkin(d["name"], phone, d["room_id"], _current_user())
    else:
        ok, msg = biz.checkin_by_customer_info(d["info"], _current_user())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/change_room", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def change_room():
    d = request.json or {}
    ok, msg = biz.change_room(d["old_room"], d["new_room"], d.get("reason", "无"), _current_user())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/change_room/request", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def change_room_request():
    d = request.json or {}
    phone = _validate_phone(d.get("phone"))
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.add_service_request(
        "换房申请",
        d.get("name"),
        phone,
        d.get("room_id"),
        d.get("target_room_id"),
        None,
        d.get("content", ""),
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/checkout", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def checkout():
    d = request.json or {}
    ok, msg, total = biz.checkout_with_details(d["room_id"], d.get("extra_items", []), _current_user())
    return jsonify({"success": ok, "message": msg, "total": total})


@app.route("/api/customer/request/change", methods=["POST"])
@_require_role("customer")
def customer_change_request():
    d = request.json or {}
    name = d.get("name")
    phone = _validate_phone(d.get("phone"))
    _, session_name, session_phone = _customer_session_identity()
    name = session_name or name
    phone = session_phone or phone
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    ok, msg = biz.add_service_request("换房申请", name, phone, d.get("room_id"), d.get("target_room_id"), None, d.get("content", ""))
    return jsonify({"success": ok, "message": msg})


@app.route("/api/customer/request/comment", methods=["POST"])
@_require_role("customer")
def customer_comment_request():
    d = request.json or {}
    name = d.get("name")
    phone = _validate_phone(d.get("phone"))
    _, session_name, session_phone = _customer_session_identity()
    name = session_name or name
    phone = session_phone or phone
    if not phone:
        return _json_bad_request("手机号必须为11位数字")
    score = int(d["score"])
    ok, msg = biz.add_service_request("投诉" if score < 2 else "评价", name, phone, d.get("room_id"), None, score, d.get("content", ""))
    return jsonify({"success": ok, "message": msg})


@app.route("/api/customer/request/clean", methods=["POST"])
@_require_role("customer")
def customer_clean_request():
    d = request.json or {}
    room_id = d.get("room_id")
    if not room_id:
        return _json_bad_request("房间号不能为空")

    name = d.get("name")
    phone = _validate_phone(d.get("phone"))
    _, session_name, session_phone = _customer_session_identity()
    name = session_name or name
    phone = session_phone or phone
    if not phone:
        return _json_bad_request("手机号必须为11位数字")

    ok, msg = biz.add_service_request("清洁申请", name, phone, room_id, None, None, d.get("content", ""))
    return jsonify({"success": ok, "message": msg})


@app.route("/api/customer/orders", methods=["POST"])
@_require_role("customer")
def customer_orders():
    d = request.json or {}
    cid, name, phone = _customer_session_identity()
    account_nickname = _current_user()
    if cid:
        rows = biz.get_customer_orders_by_cust_id(cid, account_nickname)
    else:
        body_phone = _validate_phone(d.get("phone"))
        body_name = d.get("name", "")
        rows = biz.get_customer_orders(name or body_name, phone or body_phone, account_nickname) if (phone or body_phone) else []
    return jsonify(
        _json_list(
            rows,
            ["res_id", "room_id", "room_type", "price", "checkin_date", "checkout_date", "status", "reserve_name", "reserve_phone", "account_nickname"],
            {
                "price": lambda v: float(v) if v is not None else 0,
                "checkin_date": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/reservation/orders", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def reservation_orders():
    d = request.json or {}
    rows = biz.search_reservation_orders(d.get("name", ""), d.get("phone", ""))
    return jsonify(
        _json_list(
            rows,
            ["res_id", "room_id", "room_type", "price", "checkin_date", "checkout_date", "status", "reserve_name", "reserve_phone", "account_nickname"],
            {
                "price": lambda v: float(v) if v is not None else 0,
                "checkin_date": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/checkout/orders", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def checkout_orders():
    d = request.json or {}
    rows = biz.search_active_stays(d.get("keyword", ""), d.get("name"), d.get("phone"), d.get("checkin_date"))
    return jsonify(
        _json_list(
            rows,
            ["checkin_id", "res_id", "customer", "phone", "room_id", "room_type", "price", "checkin_time", "checkout_date", "status"],
            {
                "price": lambda v: float(v) if v is not None else 0,
                "checkin_time": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/maintenance", methods=["POST"])
@_require_role("manager", "frontdesk")
def maintenance_add():
    d = request.json or {}
    ok, msg = biz.add_maintenance(d["room_id"], d["record_type"], d["handler"], d["result"], d.get("remark", ""), _current_user())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/maintenance/complete", methods=["POST"])
@_require_role("manager", "frontdesk")
def maintenance_complete():
    d = request.json or {}
    ok, msg = biz.complete_maintenance(d["room_id"], d["record_type"])
    return jsonify({"success": ok, "message": msg})


@app.route("/api/query/checkin", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def query_checkin():
    d = request.json or {}
    rows = biz.query_checkin_records(d.get("name", ""), d.get("phone", ""), d.get("checkin_date"))
    return jsonify(
        _json_list(
            rows,
            ["checkin_id", "customer", "phone", "room_id", "room_type", "price", "checkin_time", "operator", "operator_user_id", "actual_checkout_time"],
            {
                "price": float,
                "checkin_time": lambda v: str(v) if v else None,
                "actual_checkout_time": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/query/checkout", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def query_checkout():
    d = request.json or {}
    rows = biz.query_checkout_records(d.get("name", ""), d.get("phone", ""), d.get("checkout_date"))
    return jsonify(
        _json_list(
            rows,
            ["checkout_id", "customer", "phone", "room_id", "room_type", "price", "checkout_date", "checkout_time", "total_fee", "extra_fee", "operator", "operator_user_id"],
            {
                "price": float,
                "checkout_date": lambda v: str(v) if v else None,
                "checkout_time": lambda v: str(v) if v else None,
                "total_fee": float,
                "extra_fee": float,
            },
        )
    )


@app.route("/api/query/income", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def query_income():
    d = request.json or {}
    rows = biz.query_income_summary(d.get("year_month"), d.get("date"))
    if rows is None:
        return _json_bad_request("请输入月份或具体日期")
    return jsonify(
        _json_list(
            rows,
            ["period", "total_income", "checkout_count"],
            {
                "total_income": float,
            },
        )
    )


@app.route("/api/query/reservations", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def query_res():
    d = request.json or {}
    rows = biz.query_reservation_records(d.get("name", ""), d.get("phone", ""), d.get("checkin_date"))
    return jsonify(
        _json_list(
            rows,
            ["res_id", "customer", "reserve_phone", "room_id", "room_type", "price", "checkin_date", "checkout_date", "checkout_time", "status", "account_nickname"],
            {
                "price": float,
                "checkin_date": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
                "checkout_time": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/statistics", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def statistics():
    d = request.json or {}
    income, occ, hot = biz.get_statistics(d["year_month"])
    return jsonify({"income": income, "occupancy_rate": occ, "hot_type": hot})


@app.route("/api/statistics/series", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def statistics_series():
    d = request.json or {}
    return jsonify(biz.get_monthly_series(d.get("months", [])))


@app.route("/api/customer_history", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def customer_history():
    rows = biz.get_customer_history((request.json or {}).get("keyword", ""))
    return jsonify(_json_list(rows, ["checkin_id", "room_id", "checkin_time", "checkout_time", "total_fee"], {"checkin_time": str, "checkout_time": lambda v: str(v) if v else None, "total_fee": lambda v: float(v) if v else 0}))


@app.route("/api/requests")
@_require_role("manager", "receptionist", "frontdesk")
def requests_all():
    rows = biz.list_service_requests()
    return jsonify(_json_list(rows, ["request_id", "request_type", "customer_name", "customer_phone", "room_id", "target_room_id", "score", "content", "status", "handler", "response", "created_at", "handled_at"], {"created_at": str, "handled_at": lambda v: str(v) if v else None}))


@app.route("/api/requests/handle", methods=["POST"])
@_require_role("manager", "receptionist", "frontdesk")
def requests_handle():
    d = request.json or {}
    request_id = d["request_id"]
    action = d.get("action", "approve")
    response = d.get("response", "")
    req = biz.get_service_request_by_id(request_id)
    if not req:
        return jsonify({"success": False, "message": "诉求不存在"})

    _, request_type, _, _, room_id, target_room_id, _, _, status = req
    if status != "待处理":
        return jsonify({"success": False, "message": "该诉求已处理"})

    if action == "reject":
        ok = biz.reject_service_request(request_id, _current_user(), response or "已拒绝")
        return jsonify({"success": ok, "message": "已拒绝"})

    if request_type == "换房申请":
        ok, msg = biz.change_room(room_id, target_room_id, response or "客户申请换房", _current_user())
        if not ok:
            return jsonify({"success": False, "message": msg})

    ok = biz.handle_service_request(request_id, _current_user(), response or "已同意并执行")
    return jsonify({"success": ok, "message": "处理成功"})


@app.route("/api/users")
@_require_role("manager")
def users_list():
    return jsonify(_json_list(biz.get_all_employees(), ["user_id", "username", "role", "created_at"], {"created_at": str}))


@app.route("/api/users", methods=["POST"])
@_require_role("manager")
def users_add():
    d = request.json or {}
    ok, msg = biz.add_new_user(d["username"], d["password"], d["role"])
    return jsonify({"success": ok, "message": msg})


@app.route("/api/users/<int:user_id>", methods=["PUT"])
@_require_role("manager")
def users_update(user_id):
    d = request.json or {}
    ok, msg = biz.update_user_info(user_id, d["username"], d["role"])
    return jsonify({"success": ok, "message": msg})


@app.route("/api/users/<int:user_id>", methods=["DELETE"])
@_require_role("manager")
def users_delete(user_id):
    ok, msg = biz.delete_user(user_id)
    return jsonify({"success": ok, "message": msg})


@app.route("/api/customers")
@_require_role("manager")
def customers_list():
    return jsonify(_json_list(biz.list_all_customers(), ["cust_id", "name", "phone"]))


@app.route("/api/room_types")
@_require_role("manager", "receptionist", "frontdesk", "customer")
def room_types():
    return jsonify(_json_list(biz.get_room_types(), ["name", "price"], {"price": float}))


@app.route("/api/room_types", methods=["POST"])
@_require_role("manager")
def room_types_add():
    d = request.json or {}
    ok, msg = biz.add_room_type(d["name"], d["price"], _current_user())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/rooms/price", methods=["PUT"])
@_require_role("manager")
def room_price():
    d = request.json or {}
    ok, msg = biz.update_room_price(d["room_id"], d["price"], _current_user(), _current_role())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/rooms/add", methods=["POST"])
@_require_role("manager")
def room_add():
    d = request.json or {}
    ok, msg = biz.add_new_room(d["room_id"], d["room_type"], d["area"], d["price"], _current_user(), _current_role())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/rooms/batch", methods=["PUT"])
@_require_role("manager")
def room_batch():
    d = request.json or {}
    ok, msg = biz.batch_update_rooms(d["from_id"], d["to_id"], d.get("price"), d.get("status"), _current_user(), _current_role())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/rooms/<int:room_id>", methods=["PUT"])
@_require_role("manager")
def room_update(room_id):
    d = request.json or {}
    ok, msg = biz.update_room_info(
        room_id,
        d.get("room_type"),
        d.get("area"),
        d.get("price"),
        d.get("status"),
        _current_user(),
        _current_role(),
    )
    return jsonify({"success": ok, "message": msg})


@app.route("/api/reservation/room/<int:room_id>", methods=["GET"])
@_require_role("manager", "receptionist", "frontdesk")
def reservation_room(room_id):
    rows = biz.get_reservation_records_for_room(room_id)
    return jsonify(
        _json_list(
            rows,
            ["res_id", "customer", "room_id", "checkin_date", "checkout_date", "checkout_time", "status"],
            {
                "checkin_date": lambda v: str(v) if v else None,
                "checkout_date": lambda v: str(v) if v else None,
                "checkout_time": lambda v: str(v) if v else None,
            },
        )
    )


@app.route("/api/reservation/<int:res_id>/checkout_date", methods=["PUT"])
@_require_role("manager", "receptionist", "frontdesk")
def reservation_checkout_date(res_id):
    d = request.json or {}
    ok, msg = biz.update_reservation_checkout_date(res_id, d.get("checkout_date"), _current_user(), _current_role())
    return jsonify({"success": ok, "message": msg})


@app.route("/api/logs")
@_require_role("manager")
def logs():
    return jsonify(_json_list(biz.get_operation_logs(), ["operator", "operation_type", "detail", "log_time"], {"log_time": str}))


@app.route("/api/export/rooms/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_rooms():
    return _excel_response(biz.list_all_rooms(), ["房间号", "类型", "面积", "房价", "状态"], "客房信息", "rooms.xlsx")


@app.route("/api/export/reservations/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_res():
    return _excel_response(
        biz.get_reservation_records(),
        ["预订ID", "客户", "房间号", "入住日期", "离店日期", "离店时间", "状态"],
        "预订记录",
        "reservations.xlsx",
    )


@app.route("/api/export/checkin/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_checkin():
    return _excel_response(biz.get_checkin_records(), ["入住ID", "客户", "房间号", "入住时间", "经办人", "退房时间"], "入住记录", "checkin.xlsx")


@app.route("/api/export/checkout/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_checkout():
    return _excel_response(biz.get_checkout_records(), ["退房ID", "客户", "房间号", "退房时间", "总费用", "额外费用"], "退房记录", "checkout.xlsx")


@app.route("/api/export/query/rooms/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_query_rooms():
    d = request.values if request.method == "GET" else (request.json or {})
    rows = biz.advanced_room_query(
        d.get("room_id"),
        d.get("room_type"),
        d.get("status"),
        d.get("area_min"),
        d.get("area_max"),
        d.get("price_min"),
        d.get("price_max"),
        d.get("checkin_date"),
        d.get("checkout_date"),
        d.get("customer_name"),
        d.get("customer_phone"),
        d.get("checkin_time"),
    )
    return _excel_response(rows, ["房间号", "类型", "面积", "房价", "状态", "预订ID", "客户", "手机号", "入住时间", "离店日期", "操作人"], "客房信息", "query_rooms.xlsx")


@app.route("/api/export/query/reservations/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_query_reservations():
    d = request.values if request.method == "GET" else (request.json or {})
    rows = biz.query_reservation_records(d.get("name", ""), d.get("phone", ""), d.get("checkin_date"))
    return _excel_response(
        rows,
        ["预订ID", "客户", "手机号", "房间号", "房型", "房价", "入住日期", "离店日期", "离店时间", "状态"],
        "订房记录",
        "query_reservations.xlsx",
    )


@app.route("/api/export/query/checkin/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_query_checkin():
    d = request.values if request.method == "GET" else (request.json or {})
    rows = biz.query_checkin_records(d.get("name", ""), d.get("phone", ""), d.get("checkin_date"))
    return _excel_response(
        rows,
        ["入住ID", "客户", "手机号", "房间号", "房型", "房价", "入住时间", "操作人", "操作人ID", "退房时间"],
        "入住登记",
        "query_checkin.xlsx",
    )


@app.route("/api/export/query/checkout/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_query_checkout():
    d = request.values if request.method == "GET" else (request.json or {})
    rows = biz.query_checkout_records(d.get("name", ""), d.get("phone", ""), d.get("checkout_date"))
    return _excel_response(
        rows,
        ["退房ID", "客户", "手机号", "房间号", "房型", "房价", "退房日期", "退房时间", "总费用", "额外费用", "操作人", "操作人ID"],
        "退房信息",
        "query_checkout.xlsx",
    )


@app.route("/api/export/query/income/excel")
@_require_role("manager", "receptionist", "frontdesk")
def export_query_income():
    d = request.values if request.method == "GET" else (request.json or {})
    rows = biz.query_income_summary(d.get("year_month"), d.get("date")) or []
    return _excel_response(
        rows,
        ["统计周期", "总收入", "退房单数"],
        "收入汇总",
        "query_income.xlsx",
    )


@app.route("/api/backup/sql")
@_require_role("manager")
def backup_sql():
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"hotel_backup_{ts}.sql"
    out = io.BytesIO()
    cmd = [
        "mysqldump",
        "-h", os.getenv("DB_HOST", "127.0.0.1"),
        "-P", os.getenv("DB_PORT", "3306"),
        "-u", os.getenv("DB_USER", "app_user"),
        f"-p{os.getenv('DB_PASSWORD', '050810')}",
        os.getenv("DB_NAME", "hotel_management_system"),
    ]
    p = subprocess.run(cmd, capture_output=True, text=False)
    if p.returncode != 0:
        return jsonify({"success": False, "message": "备份失败，请检查 mysqldump 是否可用"}), 500
    out.write(p.stdout)
    out.seek(0)
    return send_file(out, download_name=filename, as_attachment=True)


if __name__ == "__main__":
    biz.ensure_performance_indexes()
    biz.ensure_service_request_table()
    app.run(host="0.0.0.0", port=5000, debug=True)


