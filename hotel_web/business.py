from datetime import datetime
import calendar
import re

from db_connection import DBConnection
from encryption_util import encrypt_phone, decrypt_phone

ROOM_STATUS_FREE = "空闲"
ROOM_STATUS_RESERVED = "已预订"
ROOM_STATUS_OCCUPIED = "已入住"

REQUEST_STATUS_PENDING = "待处理"
REQUEST_STATUS_DONE = "已处理"
REQUEST_STATUS_REJECTED = "已拒绝"

STATUS_ALIASES = {
    "空闲": ROOM_STATUS_FREE,
    "已预订": ROOM_STATUS_RESERVED,
    "已入住": ROOM_STATUS_OCCUPIED,
    "清洁中": "清洁中",
    "维修中": "维修中",
}


def _maintenance_room_status(record_type):
    record_type = str(record_type or "").strip()
    if record_type == "维修":
        return "维修中"
    return "清洁中"


def _db():
    conn = DBConnection().conn
    return conn, conn.cursor()


def _ensure_index(cur, table_name, index_name, create_sql):
    cur.execute(f"SHOW INDEX FROM `{table_name}` WHERE Key_name=%s", (index_name,))
    if cur.fetchone() is None:
        cur.execute(create_sql)


def normalize_status(status):
    s = str(status or "").strip()
    return STATUS_ALIASES.get(s, s)


def normalize_phone(phone):
    raw = str(phone or "").strip().replace(" ", "")
    if len(raw) != 11 or not raw.isdigit():
        return None
    return raw


def _user_id_for_username(username):
    username = str(username or "").strip()
    if not username:
        return None
    _, cur = _db()
    cur.execute("SELECT user_id FROM users WHERE username=%s LIMIT 1", (username,))
    row = cur.fetchone()
    return int(row[0]) if row else None


def mask_name(name):
    s = str(name or "")
    return (s[0] + "*" * (len(s) - 1)) if s else ""


def mask_phone(phone):
    p = normalize_phone(phone)
    if not p:
        return "*** **** ****"
    return f"{p[:3]} **** {p[-4:]}"


def _log(operator, op_type, detail):
    conn, cur = _db()
    cur.execute(
        "INSERT INTO operation_log(operator, operation_type, detail, log_time) VALUES(%s,%s,%s,%s)",
        (operator, op_type, detail, datetime.now()),
    )
    conn.commit()


def _format_operation_detail(operation_type, detail):
    text = str(detail or "").strip()
    if not text:
        return ""

    type_map = {
        "reservation": "预订",
        "batch_reservation": "批量预订",
        "cancel_reservation": "取消预订",
        "cancel_reservation_by_id": "取消预订(按单)",
        "checkin": "入住",
        "reservation_checkin": "预订入住",
        "order_checkin": "订单入住",
        "room_change": "换房",
        "order_reschedule": "订单改期",
        "checkout": "退房",
        "maintenance": "维护记录",
        "room_type": "房型管理",
        "price_change": "改价",
        "room_add": "新增客房",
        "batch_room_update": "批量修改客房",
        "room_edit": "房间编辑",
    }
    operation_type = type_map.get(str(operation_type or "").strip(), str(operation_type or "").strip())

    text = re.sub(r"\bres_id=(\d+)", r"预订单号 \1", text)
    text = re.sub(r"\bcheckin_id=(\d+)", r"入住单号 \1", text)
    text = re.sub(r"\bcheckout_date=([0-9\-: ]+)", r"退房日期 \1", text)
    text = re.sub(r"\bcheckout_time=([0-9\-: ]+)", r"退房时间 \1", text)
    text = re.sub(r"\bcheckin_date=([0-9\-: ]+)", r"入住日期 \1", text)
    text = re.sub(r"\boperator_user_id=(\d+)", r"操作人ID \1", text)
    text = re.sub(r"\btarget_room_id=(\d+)", r"目标房间 \1", text)
    text = re.sub(r"\broom_id=(\d+)", r"房间号 \1", text)
    text = re.sub(r"\broom=(\d+)", r"房间号 \1", text)

    text = text.replace("->", " 到 ")
    text = text.replace(";", "；")
    text = text.replace(",", "，")
    text = text.replace("=", "：")

    if operation_type == "房型管理":
        text = re.sub(r"^(.+?)：(.+)$", r"房型 \1，基础价格 \2", text)
    elif operation_type == "改价":
        text = re.sub(r"^房间号\s*(\d+)\s*改价\s*(.+)$", r"房间 \1 改价为 \2", text)
    elif operation_type == "新增客房":
        text = re.sub(r"^新增房间号?\s*(\d+)$", r"新增房间 \1", text)
    elif operation_type == "换房":
        text = re.sub(r"^入住单号\s*(\d+)\s*，\s*房间号\s*(\d+)\s* 到 \s*(\d+)$", r"入住单 \1，房间 \2 换到 \3", text)
    elif operation_type == "订单改期":
        text = re.sub(r"^预订单号\s*(\d+)\s*，\s*退房日期\s*(.+)$", r"订单 \1，退房日期 \2", text)

    return text


def ensure_service_request_table():
    conn, cur = _db()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS service_request (
            request_id INT AUTO_INCREMENT PRIMARY KEY,
            request_type VARCHAR(30) NOT NULL,
            customer_name VARCHAR(100) NOT NULL,
            customer_phone VARCHAR(255) NOT NULL,
            room_id INT NULL,
            target_room_id INT NULL,
            score INT NULL,
            content VARCHAR(500) NULL,
            status VARCHAR(20) NOT NULL DEFAULT '待处理',
            handler VARCHAR(100) NULL,
            response VARCHAR(500) NULL,
            created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
            handled_at DATETIME NULL
        )
        """
    )
    conn.commit()


def _month_bounds(year_month):
    ym = str(year_month or "").strip()
    if not ym:
        return None, None
    try:
        y, m = map(int, ym.split("-"))
        start = datetime(y, m, 1)
        if m == 12:
            end = datetime(y + 1, 1, 1)
        else:
            end = datetime(y, m + 1, 1)
        return start, end
    except Exception:
        return None, None


def _day_bounds(date_value):
    day = _parse_date_value(date_value)
    if not day:
        return None, None
    start = datetime(day.year, day.month, day.day)
    end = datetime(day.year, day.month, day.day, 23, 59, 59, 999999)
    return start, end


def ensure_performance_indexes():
    conn, cur = _db()
    changed = False
    try:
        _ensure_index(
            cur,
            "service_request",
            "idx_service_request_created_at",
            "CREATE INDEX idx_service_request_created_at ON service_request(created_at)",
        )
        changed = True
    except Exception:
        conn.rollback()
        return
    try:
        _ensure_index(
            cur,
            "service_request",
            "idx_service_request_status",
            "CREATE INDEX idx_service_request_status ON service_request(status)",
        )
        changed = True
    except Exception:
        conn.rollback()
        return
    try:
        _ensure_index(
            cur,
            "checkin",
            "idx_checkin_checkin_time",
            "CREATE INDEX idx_checkin_checkin_time ON checkin(checkin_time)",
        )
        changed = True
    except Exception:
        conn.rollback()
        return
    try:
        _ensure_index(
            cur,
            "checkout",
            "idx_checkout_checkout_time",
            "CREATE INDEX idx_checkout_checkout_time ON checkout(checkout_time)",
        )
        changed = True
    except Exception:
        conn.rollback()
        return
    try:
        _ensure_index(
            cur,
            "reservation",
            "idx_reservation_checkin_date",
            "CREATE INDEX idx_reservation_checkin_date ON reservation(checkin_date)",
        )
        changed = True
    except Exception:
        conn.rollback()
        return
    if changed:
        conn.commit()



def ensure_reservation_columns():
    conn, cur = _db()
    cur.execute("SHOW COLUMNS FROM reservation LIKE 'checkout_date'")
    has_checkout_date = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM reservation LIKE 'checkout_time'")
    has_checkout_time = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM reservation LIKE 'reserve_name'")
    has_reserve_name = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM reservation LIKE 'reserve_phone_encrypted'")
    has_reserve_phone = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM reservation LIKE 'account_nickname'")
    has_account_nickname = cur.fetchone() is not None
    if not has_checkout_date:
        cur.execute("ALTER TABLE reservation ADD COLUMN checkout_date DATE NULL AFTER checkin_date")
    if not has_checkout_time:
        cur.execute("ALTER TABLE reservation ADD COLUMN checkout_time DATETIME NULL AFTER checkout_date")
    if not has_reserve_name:
        cur.execute("ALTER TABLE reservation ADD COLUMN reserve_name VARCHAR(100) NULL AFTER cust_id")
    if not has_reserve_phone:
        cur.execute("ALTER TABLE reservation ADD COLUMN reserve_phone_encrypted VARCHAR(255) NULL AFTER reserve_name")
    if not has_account_nickname:
        cur.execute("ALTER TABLE reservation ADD COLUMN account_nickname VARCHAR(100) NULL AFTER reserve_phone_encrypted")
    if (not has_checkout_date) or (not has_checkout_time) or (not has_reserve_name) or (not has_reserve_phone) or (not has_account_nickname):
        conn.commit()


def ensure_checkin_checkout_columns():
    conn, cur = _db()
    changed = False

    cur.execute("SHOW COLUMNS FROM checkin LIKE 'checkin_date'")
    has_checkin_date = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM checkin LIKE 'operator_user_id'")
    has_checkin_operator_user_id = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM checkout LIKE 'checkin_date'")
    has_checkout_checkin_date = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM checkout LIKE 'operator'")
    has_checkout_operator = cur.fetchone() is not None
    cur.execute("SHOW COLUMNS FROM checkout LIKE 'operator_user_id'")
    has_checkout_operator_user_id = cur.fetchone() is not None

    if not has_checkin_date:
        cur.execute("ALTER TABLE checkin ADD COLUMN checkin_date DATE NULL AFTER checkin_time")
        changed = True
    if not has_checkin_operator_user_id:
        cur.execute("ALTER TABLE checkin ADD COLUMN operator_user_id INT NULL AFTER operator")
        changed = True
    if not has_checkout_checkin_date:
        cur.execute("ALTER TABLE checkout ADD COLUMN checkin_date DATE NULL AFTER checkout_time")
        changed = True
    if not has_checkout_operator:
        cur.execute("ALTER TABLE checkout ADD COLUMN operator VARCHAR(50) NULL AFTER extra_fee")
        changed = True
    if not has_checkout_operator_user_id:
        cur.execute("ALTER TABLE checkout ADD COLUMN operator_user_id INT NULL AFTER operator")
        changed = True

    if changed:
        conn.commit()


def ensure_user_role_enum():
    conn, cur = _db()
    try:
        cur.execute("SHOW COLUMNS FROM users LIKE 'role'")
        row = cur.fetchone()
        if not row:
            return
        column_type = str(row[1] or "").lower()
        if "frontdesk" not in column_type:
            cur.execute("ALTER TABLE users MODIFY COLUMN role ENUM('manager','receptionist','frontdesk') NOT NULL COMMENT '角色'")
            conn.commit()
    except Exception:
        conn.rollback()


def _parse_date_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _parse_datetime_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text, fmt)
        except Exception:
            continue
    return None


def _date_ranges_overlap(start_a, end_a, start_b, end_b):
    if not start_a or not end_a or not start_b or not end_b:
        return False
    return start_a < end_b and start_b < end_a


def _has_active_checkin(cur, room_id):
    cur.execute("SELECT 1 FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL LIMIT 1", (room_id,))
    return cur.fetchone() is not None


def _room_has_date_conflict(cur, room_id, checkin_date, checkout_date):
    cur.execute(
        "SELECT checkin_date, checkout_date FROM reservation "
        "WHERE room_id=%s AND status IN (%s,%s) AND checkin_date IS NOT NULL AND checkout_date IS NOT NULL",
        (room_id, ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED),
    )
    for row in cur.fetchall():
        existing_checkin = _parse_date_value(row[0])
        existing_checkout = _parse_date_value(row[1])
        if _date_ranges_overlap(checkin_date, checkout_date, existing_checkin, existing_checkout):
            return True, f"该房间在 {existing_checkin} 至 {existing_checkout} 已被占用"
    return False, ""


def _room_status_for_query(cur, room_id, room_status, checkin_date=None, checkout_date=None):
    current_status = normalize_status(room_status)
    if not checkin_date or not checkout_date:
        return current_status
    if _has_active_checkin(cur, room_id):
        return ROOM_STATUS_OCCUPIED
    conflict, _ = _room_has_date_conflict(cur, room_id, checkin_date, checkout_date)
    if conflict:
        return ROOM_STATUS_RESERVED
    return ROOM_STATUS_FREE


def _active_stay_rows(cur=None):
    own_cursor = False
    if cur is None:
        _, cur = _db()
        own_cursor = True
    cur.execute(
        "SELECT c.room_id, c.checkin_id, cu.name, cu.phone_encrypted, c.checkin_time, c.operator, "
        "rm.room_type, rm.price, "
        "r.res_id, r.checkout_date, r.status "
        "FROM checkin c "
        "JOIN customer cu ON c.cust_id=cu.cust_id "
        "JOIN room rm ON c.room_id=rm.room_id "
        "LEFT JOIN ("
        "    SELECT rr1.cust_id, rr1.room_id, rr1.res_id, rr1.checkout_date, rr1.status "
        "    FROM reservation rr1 "
        "    JOIN ("
        "        SELECT cust_id, room_id, MAX(res_id) AS res_id "
        "        FROM reservation "
        "        WHERE status<>'已取消' "
        "        GROUP BY cust_id, room_id"
        "    ) latest ON latest.res_id = rr1.res_id"
        ") r ON r.cust_id=c.cust_id AND r.room_id=c.room_id "
        "WHERE c.actual_checkout_time IS NULL "
        "ORDER BY c.checkin_time DESC"
    )
    rows = []
    for row in cur.fetchall():
        room_id, checkin_id, name, phone_enc, checkin_time, operator, room_type, price, res_id, checkout_date, res_status = row
        try:
            real_phone = decrypt_phone(phone_enc) if phone_enc else ""
        except Exception:
            real_phone = ""
        rows.append({
            "room_id": room_id,
            "checkin_id": checkin_id,
            "customer": name,
            "phone": real_phone,
            "checkin_time": checkin_time,
            "operator": operator,
            "room_type": room_type,
            "price": float(price) if price is not None else 0,
            "res_id": res_id,
            "checkout_date": checkout_date,
            "res_status": res_status or "已入住",
        })
    if own_cursor:
        try:
            cur.close()
        except Exception:
            pass
    return rows
def verify_user(username, password):
    _, cur = _db()
    cur.execute("SELECT role FROM users WHERE username=%s AND password=%s", (username, password))
    return cur.fetchone()


def get_or_create_customer_identity(name, phone):
    phone = normalize_phone(phone)
    if not phone:
        raise ValueError("手机号必须为11位数字")
    conn, cur = _db()
    cur.execute("SELECT cust_id, name, phone_encrypted FROM customer")
    for cid, cname, enc in cur.fetchall():
        try:
            if decrypt_phone(enc) == phone:
                return cid, cname
        except Exception:
            pass
    cur.execute("INSERT INTO customer(name, phone_encrypted) VALUES(%s,%s)", (name, encrypt_phone(phone)))
    conn.commit()
    return cur.lastrowid, name


def _find_customer(info):
    info = str(info or "").strip()
    _, cur = _db()
    p = normalize_phone(info)
    if p:
        cur.execute("SELECT cust_id, name, phone_encrypted FROM customer")
        for cid, name, enc in cur.fetchall():
            try:
                if decrypt_phone(enc) == p:
                    return cid, name
            except Exception:
                continue
    cur.execute("SELECT cust_id, name FROM customer WHERE name LIKE %s LIMIT 1", (f"%{info}%",))
    row = cur.fetchone()
    return row if row else (None, None)


def _find_customer_by_name_phone(name, phone):
    p = normalize_phone(phone)
    if not p:
        return (None, None)
    _, cur = _db()
    cur.execute("SELECT cust_id, name, phone_encrypted FROM customer")
    for cid, cname, enc in cur.fetchall():
        try:
            if str(cname) == str(name) and decrypt_phone(enc) == p:
                return cid, cname
        except Exception:
            continue
    return (None, None)


def list_all_customers():
    _, cur = _db()
    cur.execute("SELECT cust_id, name, phone_encrypted FROM customer ORDER BY cust_id DESC")
    out = []
    for cid, name, enc in cur.fetchall():
        try:
            phone = decrypt_phone(enc)
        except Exception:
            phone = ""
        out.append((cid, mask_name(name), mask_phone(phone)))
    return out


def list_all_rooms():
    _, cur = _db()
    cur.execute("SELECT room_id, room_type, area, price, status FROM room ORDER BY room_id")
    return [(a, b, c, d, normalize_status(e)) for a, b, c, d, e in cur.fetchall()]


def room_exists(room_id):
    _, cur = _db()
    cur.execute("SELECT 1 FROM room WHERE room_id=%s", (room_id,))
    return cur.fetchone() is not None


def _sync_room_status(cur, room_id):
    cur.execute("SELECT 1 FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL LIMIT 1", (room_id,))
    if cur.fetchone():
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_OCCUPIED, room_id))
        return ROOM_STATUS_OCCUPIED

    cur.execute("SELECT COUNT(*) FROM reservation WHERE room_id=%s AND status=%s", (room_id, ROOM_STATUS_RESERVED))
    if int(cur.fetchone()[0] or 0) > 0:
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_RESERVED, room_id))
        return ROOM_STATUS_RESERVED

    cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_FREE, room_id))
    return ROOM_STATUS_FREE


def make_reservation(name, phone, room_id, checkin_date, operator, checkout_date=None, checkout_time=None, account_nickname=None, customer_cust_id=None):
    ensure_reservation_columns()
    name = str(name or "").strip()
    if not name:
        return False, "姓名不能为空"
    phone = normalize_phone(phone)
    if not phone:
        return False, "手机号必须为11位数字"

    parsed_checkin_date = _parse_date_value(checkin_date)
    if not parsed_checkin_date:
        return False, "入住日期格式不正确"
    today = datetime.now().date()
    if parsed_checkin_date < today:
        return False, "入住日期不能早于今天"

    parsed_checkout_date = _parse_date_value(checkout_date)
    if checkout_date not in (None, "") and not parsed_checkout_date:
        return False, "离店日期格式不正确"
    if not parsed_checkout_date:
        return False, "离店日期必填"
    if parsed_checkout_date <= today:
        return False, "离店日期必须晚于今天"

    parsed_checkout_time = _parse_datetime_value(checkout_time)
    if checkout_time not in (None, "") and not parsed_checkout_time:
        return False, "离店时间格式不正确"

    if parsed_checkout_date and parsed_checkout_date < parsed_checkin_date:
        return False, "离店日期不能早于入住日期"

    if parsed_checkout_time and parsed_checkout_time <= datetime.combine(parsed_checkin_date, datetime.min.time()):
        return False, "离店时间必须晚于入住日期"

    if (not parsed_checkout_date) and parsed_checkout_time:
        parsed_checkout_date = parsed_checkout_time.date()

    if not room_exists(room_id):
        return False, "房间不存在"

    conn, cur = _db()
    try:
        cur.execute("SELECT status FROM room WHERE room_id=%s", (room_id,))
        row = cur.fetchone()
        if not row:
            return False, "房间不存在"
        current_status = _room_status_for_query(cur, room_id, row[0], parsed_checkin_date, parsed_checkout_date)
        if current_status != ROOM_STATUS_FREE:
            conflict, conflict_msg = _room_has_date_conflict(cur, room_id, parsed_checkin_date, parsed_checkout_date)
            if conflict:
                return False, conflict_msg
            if _has_active_checkin(cur, room_id):
                return False, "该房间当前正在入住，无法预订所选日期"
            return False, f"房间状态为 {current_status}，不可预订"

        if customer_cust_id is not None:
            try:
                cid = int(customer_cust_id)
            except Exception:
                return False, "账号客户信息无效"
        else:
            cid, _ = get_or_create_customer_identity(name, phone)
        account_nickname = str(account_nickname or "").strip() or None
        cur.execute(
            "INSERT INTO reservation(room_id,cust_id,reserve_name,reserve_phone_encrypted,account_nickname,checkin_date,checkout_date,checkout_time,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            (room_id, cid, name, encrypt_phone(phone), account_nickname, parsed_checkin_date, parsed_checkout_date, parsed_checkout_time, ROOM_STATUS_RESERVED),
        )
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_RESERVED, room_id))
        conn.commit()
        _log(operator, "预订", f"{name} 预订房间 {room_id}")
        return True, "预订成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)
def make_reservation_by_type(name, phone, room_type, quantity, checkin_date, operator, checkout_date=None, account_nickname=None, customer_cust_id=None):
    ensure_reservation_columns()
    name = str(name or "").strip()
    if not name:
        return False, "姓名不能为空"
    phone = normalize_phone(phone)
    if not phone:
        return False, "手机号必须为11位数字"

    parsed_checkin_date = _parse_date_value(checkin_date)
    if not parsed_checkin_date:
        return False, "入住日期格式不正确"
    today = datetime.now().date()
    if parsed_checkin_date < today:
        return False, "入住日期不能早于今天"

    parsed_checkout_date = _parse_date_value(checkout_date)
    if checkout_date not in (None, "") and not parsed_checkout_date:
        return False, "离店日期格式不正确"
    if not parsed_checkout_date:
        return False, "离店日期必填"
    if parsed_checkout_date <= today:
        return False, "离店日期必须晚于今天"
    if parsed_checkout_date and parsed_checkout_date < parsed_checkin_date:
        return False, "离店日期不能早于入住日期"

    conn, cur = _db()
    try:
        quantity = int(quantity)
        if quantity <= 0:
            return False, "数量必须大于0"

        cur.execute("SELECT room_id, status FROM room WHERE room_type=%s ORDER BY room_id", (room_type,))
        free_ids = []
        for rid, rstatus in cur.fetchall():
            final_status = _room_status_for_query(cur, rid, rstatus, parsed_checkin_date, parsed_checkout_date)
            conflict, conflict_msg = _room_has_date_conflict(cur, rid, parsed_checkin_date, parsed_checkout_date)
            if final_status == ROOM_STATUS_FREE:
                free_ids.append(rid)
            elif conflict:
                continue
        if len(free_ids) < quantity:
            return False, "可预订房间不足"

        if customer_cust_id is not None:
            try:
                cid = int(customer_cust_id)
            except Exception:
                return False, "账号客户信息无效"
        else:
            cid, _ = get_or_create_customer_identity(name, phone)
        account_nickname = str(account_nickname or "").strip() or None
        for rid in free_ids[:quantity]:
            cur.execute(
                "INSERT INTO reservation(room_id,cust_id,reserve_name,reserve_phone_encrypted,account_nickname,checkin_date,checkout_date,checkout_time,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                (rid, cid, name, encrypt_phone(phone), account_nickname, parsed_checkin_date, parsed_checkout_date, None, ROOM_STATUS_RESERVED),
            )
            cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_RESERVED, rid))

        conn.commit()
        _log(operator, "批量预订", f"{name} 预订 {quantity} 间 {room_type}")
        return True, "批量预订成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)
def cancel_reservation(info, operator):
    cid, name = _find_customer(info)
    if not cid:
        return False, "未找到客户"
    conn, cur = _db()
    try:
        cur.execute("SELECT room_id FROM reservation WHERE cust_id=%s AND status=%s", (cid, ROOM_STATUS_RESERVED))
        room_ids = [int(x[0]) for x in cur.fetchall()]
        cur.execute("UPDATE reservation SET status='已取消' WHERE cust_id=%s AND status='已预订'", (cid,))
        affected = cur.rowcount
        for rid in room_ids:
            cur.execute("SELECT 1 FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL LIMIT 1", (rid,))
            occupied = cur.fetchone() is not None
            if not occupied:
                cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_FREE, rid))
        conn.commit()
        _log(operator, "取消预订", f"{name} 取消 {affected} 条预订")
        return True, f"已取消 {name} 的有效预订"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def cancel_reservation_by_res_id(res_id, name, phone, operator, require_owner=True):
    try:
        res_id = int(res_id)
    except Exception:
        return False, "订单号无效"

    owner_cid = None
    if require_owner:
        owner_cid, _ = _find_customer_by_name_phone(name, phone)
        if not owner_cid:
            return False, "客户信息不匹配"

    conn, cur = _db()
    try:
        cur.execute("SELECT room_id, cust_id, status FROM reservation WHERE res_id=%s LIMIT 1", (res_id,))
        row = cur.fetchone()
        if not row:
            return False, "订单不存在"
        room_id, cid, status = row
        if require_owner and int(cid) != int(owner_cid):
            return False, "无权取消该订单"
        if normalize_status(status) != ROOM_STATUS_RESERVED:
            return False, "该订单当前不可取消"

        cur.execute("UPDATE reservation SET status=%s WHERE res_id=%s AND status=%s", ("已取消", res_id, ROOM_STATUS_RESERVED))
        if cur.rowcount == 0:
            return False, "订单取消失败"

        cur.execute("SELECT COUNT(*) FROM reservation WHERE room_id=%s AND status=%s", (room_id, ROOM_STATUS_RESERVED))
        active_reserved = int(cur.fetchone()[0] or 0)
        cur.execute("SELECT COUNT(*) FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL", (room_id,))
        active_checkin = int(cur.fetchone()[0] or 0)
        if active_checkin > 0:
            cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_OCCUPIED, room_id))
        elif active_reserved > 0:
            cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_RESERVED, room_id))
        else:
            cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_FREE, room_id))

        conn.commit()
        _log(operator, "取消预订(按单)", f"res_id={res_id}, room={room_id}")
        return True, "订单取消成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def direct_checkin(name, phone, room_id, operator):
    phone = normalize_phone(phone)
    if not phone:
        return False, "手机号必须为11位数字"
    ensure_checkin_checkout_columns()
    conn, cur = _db()
    try:
        cur.execute("SELECT status FROM room WHERE room_id=%s", (room_id,))
        row = cur.fetchone()
        if not row:
            return False, "房间不存在"
        if normalize_status(row[0]) != ROOM_STATUS_FREE:
            return False, f"房间状态为 {normalize_status(row[0])}，不可入住"
        cid, _ = get_or_create_customer_identity(name, phone)
        now = datetime.now()
        cur.execute(
            "INSERT INTO checkin(room_id,cust_id,checkin_time,checkin_date,operator,operator_user_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (room_id, cid, now, now.date(), operator, _user_id_for_username(operator)),
        )
        _sync_room_status(cur, room_id)
        conn.commit()
        _log(operator, "入住", f"{name} 入住房间 {room_id}")
        return True, "入住成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def checkin_by_customer_info(info, operator):
    ensure_checkin_checkout_columns()
    cid, name = _find_customer(info)
    if not cid:
        return False, "未找到客户"
    conn, cur = _db()
    try:
        cur.execute("SELECT room_id FROM reservation WHERE cust_id=%s AND status='已预订' LIMIT 1", (cid,))
        row = cur.fetchone()
        if not row:
            return False, "无有效预订"
        room_id = row[0]
        now = datetime.now()
        cur.execute(
            "INSERT INTO checkin(room_id,cust_id,checkin_time,checkin_date,operator,operator_user_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (room_id, cid, now, now.date(), operator, _user_id_for_username(operator)),
        )
        cur.execute("UPDATE reservation SET status='已入住' WHERE cust_id=%s AND room_id=%s AND status='已预订'", (cid, room_id))
        _sync_room_status(cur, room_id)
        conn.commit()
        _log(operator, "预订入住", f"{name} 入住房间 {room_id}")
        return True, "入住成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def checkin_by_reservation_id(res_id, operator):
    try:
        res_id = int(res_id)
    except Exception:
        return False, "订单号无效"
    conn, cur = _db()
    try:
        ensure_checkin_checkout_columns()
        cur.execute(
            "SELECT room_id, cust_id, status FROM reservation WHERE res_id=%s LIMIT 1",
            (res_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, "订单不存在"
        room_id, cid, status = row
        if normalize_status(status) != ROOM_STATUS_RESERVED:
            return False, "该订单当前不可办理入住"

        cur.execute(
            "SELECT 1 FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL LIMIT 1",
            (room_id,),
        )
        if cur.fetchone():
            return False, "该房间当前已有在住记录"

        cur.execute(
            "INSERT INTO checkin(room_id,cust_id,checkin_time,checkin_date,operator,operator_user_id) VALUES(%s,%s,%s,%s,%s,%s)",
            (room_id, cid, datetime.now(), datetime.now().date(), operator, _user_id_for_username(operator)),
        )
        cur.execute(
            "UPDATE reservation SET status=%s WHERE res_id=%s AND status=%s",
            (ROOM_STATUS_OCCUPIED, res_id, ROOM_STATUS_RESERVED),
        )
        _sync_room_status(cur, room_id)
        conn.commit()
        _log(operator, "订单入住", f"res_id={res_id}, room={room_id}")
        return True, "入住成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def change_room(old_room_id, new_room_id, reason, operator):
    conn, cur = _db()
    try:
        cur.execute("SELECT checkin_id, cust_id FROM checkin WHERE room_id=%s AND actual_checkout_time IS NULL LIMIT 1", (old_room_id,))
        row = cur.fetchone()
        if not row:
            return False, "原房间无在住客户"
        checkin_id, cid = row
        cur.execute("SELECT status FROM room WHERE room_id=%s", (new_room_id,))
        ns = cur.fetchone()
        if not ns or normalize_status(ns[0]) != ROOM_STATUS_FREE:
            return False, "新房间不可用"
        cur.execute(
            "SELECT res_id FROM reservation WHERE cust_id=%s AND room_id=%s AND status IN (%s,%s) ORDER BY res_id DESC LIMIT 1",
            (cid, old_room_id, ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED),
        )
        res_row = cur.fetchone()
        cur.execute(
            "INSERT INTO room_change(old_room_id,new_room_id,cust_id,change_time,reason) VALUES(%s,%s,%s,%s,%s)",
            (old_room_id, new_room_id, cid, datetime.now(), reason),
        )
        cur.execute("UPDATE checkin SET room_id=%s WHERE cust_id=%s AND actual_checkout_time IS NULL", (new_room_id, cid))
        if res_row and res_row[0]:
            cur.execute("UPDATE reservation SET room_id=%s, status=%s WHERE res_id=%s", (new_room_id, ROOM_STATUS_OCCUPIED, res_row[0]))
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_FREE, old_room_id))
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (ROOM_STATUS_OCCUPIED, new_room_id))
        conn.commit()
        _log(operator, "换房", f"checkin_id={checkin_id}, {old_room_id}->{new_room_id}")
        return True, "换房成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def update_reservation_checkout_date(res_id, new_checkout_date, operator, role):
    if role not in {"manager", "receptionist"}:
        return False, "权限不足"
    try:
        res_id = int(res_id)
    except Exception:
        return False, "订单号无效"

    parsed_checkout_date = _parse_date_value(new_checkout_date)
    if not parsed_checkout_date:
        return False, "离店日期格式不正确"

    conn, cur = _db()
    try:
        cur.execute(
            "SELECT room_id, checkin_date, checkout_time, status FROM reservation WHERE res_id=%s LIMIT 1",
            (res_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, "订单不存在"
        room_id, checkin_date, checkout_time, status = row
        checkin_date = _parse_date_value(checkin_date)
        if not checkin_date:
            return False, "入住日期无效"
        today = datetime.now().date()
        if parsed_checkout_date <= today:
            return False, "离店日期必须晚于今天"
        if parsed_checkout_date < checkin_date:
            return False, "离店日期不能早于入住日期"

        parsed_checkout_time = None
        if checkout_time:
            old_checkout_time = _parse_datetime_value(checkout_time)
            if old_checkout_time:
                parsed_checkout_time = datetime.combine(parsed_checkout_date, old_checkout_time.time())

        cur.execute(
            "UPDATE reservation SET checkout_date=%s, checkout_time=%s WHERE res_id=%s",
            (parsed_checkout_date, parsed_checkout_time, res_id),
        )
        _sync_room_status(cur, room_id)
        conn.commit()
        _log(operator, "订单改期", f"res_id={res_id}, checkout_date={parsed_checkout_date}")
        return True, "离店日期已更新"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def checkout_with_details(room_id, extra_items, operator, auto_clean=True):
    ensure_reservation_columns()
    ensure_checkin_checkout_columns()
    conn, cur = _db()
    try:
        cur.execute(
            "SELECT c.cust_id, r.price, cu.name, c.checkin_time, c.checkin_date FROM checkin c JOIN room r ON c.room_id=r.room_id "
            "JOIN customer cu ON c.cust_id=cu.cust_id WHERE c.room_id=%s AND c.actual_checkout_time IS NULL LIMIT 1",
            (room_id,),
        )
        row = cur.fetchone()
        if not row:
            return False, "无在住记录", 0

        cid, base_price, cname, checkin_time, stored_checkin_date = row

        cur.execute(
            "SELECT res_id, checkin_date, checkout_date FROM reservation "
            "WHERE cust_id=%s AND room_id=%s AND status IN (%s,%s) ORDER BY res_id DESC LIMIT 1",
            (cid, room_id, ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED),
        )
        res_row = cur.fetchone()

        nights = 1
        fallback_note = ""
        if res_row and res_row[1] and res_row[2]:
            checkin_date = _parse_date_value(res_row[1])
            checkout_date = _parse_date_value(res_row[2])
            if checkin_date and checkout_date:
                nights = max(1, (checkout_date - checkin_date).days)
            else:
                fallback_note = "（未找到完整离店日期，按1晚计费）"
        else:
            fallback_note = "（未找到完整离店日期，按1晚计费）"

        room_fee = float(base_price) * nights
        parsed_extra_items = []
        for item in extra_items or []:
            label = ""
            raw_amount = 0
            if isinstance(item, dict):
                label = str(item.get("name") or item.get("label") or item.get("item") or item.get("content") or "").strip()
                raw_amount = item.get("amount", item.get("fee", item.get("value", 0)))
            elif isinstance(item, (list, tuple)):
                if len(item) >= 2:
                    label = str(item[0]).strip()
                    raw_amount = item[1]
                elif len(item) == 1:
                    label = str(item[0]).strip()
            else:
                label = str(item).strip()
            try:
                amount = float(raw_amount)
            except Exception:
                amount = 0
            if label or amount:
                parsed_extra_items.append((label, amount))
        extra_total = sum(amount for _, amount in parsed_extra_items)
        total = room_fee + extra_total

        now = datetime.now()
        cur.execute(
            "INSERT INTO checkout(room_id,cust_id,checkout_time,checkin_date,total_fee,extra_fee,operator,operator_user_id) VALUES(%s,%s,%s,%s,%s,%s,%s,%s)",
            (room_id, cid, now, stored_checkin_date or (checkin_time.date() if checkin_time else now.date()), total, extra_total, operator, _user_id_for_username(operator)),
        )
        cur.execute(
            "UPDATE checkin SET actual_checkout_time=%s WHERE room_id=%s AND cust_id=%s AND actual_checkout_time IS NULL",
            (now, room_id, cid),
        )

        cur.execute(
            "UPDATE reservation SET status=%s WHERE cust_id=%s AND room_id=%s AND status IN (%s,%s)",
            ("已退房", cid, room_id, ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED),
        )

        if auto_clean:
            cur.execute(
                "INSERT INTO room_maintenance_clean(room_id,record_type,record_time,handler,result,remark) VALUES(%s,%s,%s,%s,%s,%s)",
                (room_id, "清洁", now, operator, "待清洁", "退房自动生成"),
            )
            cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (_maintenance_room_status("清洁"), room_id))
        else:
            _sync_room_status(cur, room_id)

        conn.commit()
        _log(operator, "退房", f"{cname} 退房 {room_id} 总费用 {total}")

        message = f"退房成功，总金额 {total:.2f}（房费={float(base_price):.2f}×{nights}晚 + 额外费用{extra_total:.2f}）{fallback_note}"
        return True, message, total
    except Exception as e:
        conn.rollback()
        return False, str(e), 0


def query_income_records(name="", phone="", checkin_date=None):
    return query_checkout_records(name, phone, checkin_date)


def query_income_summary(year_month=None, date=None):
    _, cur = _db()
    ym = str(year_month or "").strip()
    day = _parse_date_value(date)
    if ym:
        start, end = _month_bounds(ym)
        if not start or not end:
            return []
        cur.execute(
            "SELECT %s AS period, IFNULL(SUM(total_fee),0) AS total_income, COUNT(*) AS checkout_count "
            "FROM checkout WHERE checkout_time>=%s AND checkout_time<%s",
            (ym, start, end),
        )
        rows = cur.fetchall()
        return [(row[0], float(row[1] or 0), int(row[2] or 0)) for row in rows]
    if day:
        period = day.strftime("%Y-%m-%d")
        start, end = _day_bounds(day)
        if not start or not end:
            return []
        cur.execute(
            "SELECT %s AS period, IFNULL(SUM(total_fee),0) AS total_income, COUNT(*) AS checkout_count "
            "FROM checkout WHERE checkout_time>=%s AND checkout_time<=%s",
            (period, start, end),
        )
        rows = cur.fetchall()
        return [(row[0], float(row[1] or 0), int(row[2] or 0)) for row in rows]
    cur.execute(
        "SELECT '全部' AS period, IFNULL(SUM(total_fee),0) AS total_income, COUNT(*) AS checkout_count "
        "FROM checkout"
    )
    row = cur.fetchone()
    return [("全部", float(row[1] or 0), int(row[2] or 0))] if row else [("全部", 0.0, 0)]


def get_reservation_records_for_room(room_id):
    ensure_reservation_columns()
    _, cur = _db()
    cur.execute(
        "SELECT r.res_id, IFNULL(r.reserve_name, c.name), r.room_id, r.checkin_date, r.checkout_date, r.checkout_time, r.status "
        "FROM reservation r JOIN customer c ON r.cust_id=c.cust_id "
        "WHERE r.room_id=%s AND r.status IN (%s,%s) ORDER BY r.res_id DESC",
        (room_id, ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED),
    )
    return cur.fetchall()


def query_reservation_records(name="", phone="", checkin_date=None):
    ensure_reservation_columns()
    name = str(name or "").strip()
    phone = normalize_phone(phone)
    q_checkin_date = _parse_date_value(checkin_date)
    _, cur = _db()
    sql = (
        "SELECT r.res_id, IFNULL(r.reserve_name, c.name), r.room_id, rm.room_type, rm.price, r.checkin_date, r.checkout_date, "
        "COALESCE(r.checkout_time, co.checkout_time) AS checkout_time, r.status, "
        "r.reserve_phone_encrypted, IFNULL(r.account_nickname, '') "
        "FROM reservation r "
        "JOIN customer c ON r.cust_id=c.cust_id "
        "JOIN room rm ON r.room_id=rm.room_id "
        "LEFT JOIN checkout co ON co.checkout_id = ("
        "SELECT cc.checkout_id FROM checkout cc "
        "WHERE cc.cust_id=r.cust_id AND cc.room_id=r.room_id "
        "ORDER BY cc.checkout_time DESC LIMIT 1"
        ") "
    )
    where = []
    params = []
    if q_checkin_date:
        where.append("r.checkin_date=%s")
        params.append(q_checkin_date)
    if name:
        where.append("(IFNULL(r.reserve_name, c.name) LIKE %s OR c.name LIKE %s)")
        params.extend([f"%{name}%", f"%{name}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.res_id DESC"
    cur.execute(sql, params)
    out = []
    for row in cur.fetchall():
        res_id, customer, room_id, room_type, price, row_checkin_date, checkout_date, checkout_time, status, reserve_phone_enc, account_nickname = row
        try:
            reserve_phone = decrypt_phone(reserve_phone_enc) if reserve_phone_enc else ""
        except Exception:
            reserve_phone = ""
        if name and name not in str(customer or ""):
            continue
        if phone and reserve_phone != phone:
            continue
        if q_checkin_date and _parse_date_value(row_checkin_date) != q_checkin_date:
            continue
        out.append((res_id, customer, mask_phone(reserve_phone) if reserve_phone else "", room_id, room_type, float(price) if price is not None else 0, row_checkin_date, checkout_date, checkout_time, status, account_nickname))
    return out


def query_checkin_records(name="", phone="", checkin_date=None):
    ensure_checkin_checkout_columns()
    name = str(name or "").strip()
    phone = normalize_phone(phone)
    q_checkin_date = _parse_date_value(checkin_date)
    _, cur = _db()
    sql = (
        "SELECT c.checkin_id, c.cust_id, c.room_id, rm.room_type, rm.price, c.checkin_time, c.operator, "
        "COALESCE(c.operator_user_id, co.operator_user_id, u.user_id) AS operator_user_id, "
        "COALESCE(c.actual_checkout_time, co.checkout_time) AS actual_checkout_time, "
        "IFNULL(r.reserve_name, cu.name), r.reserve_phone_encrypted "
        "FROM checkin c "
        "JOIN customer cu ON c.cust_id=cu.cust_id "
        "LEFT JOIN users u ON u.username=c.operator "
        "LEFT JOIN checkout co ON co.checkout_id = ("
        "SELECT cc.checkout_id FROM checkout cc "
        "WHERE cc.cust_id=c.cust_id AND cc.room_id=c.room_id "
        "ORDER BY cc.checkout_time DESC LIMIT 1"
        ") "
        "LEFT JOIN reservation r ON r.res_id = ("
        "SELECT rr.res_id FROM reservation rr "
        "WHERE rr.cust_id=c.cust_id AND rr.room_id=c.room_id AND rr.status<>'已取消' "
        "ORDER BY rr.res_id DESC LIMIT 1"
        ") "
        "JOIN room rm ON c.room_id=rm.room_id "
    )
    where = []
    params = []
    if q_checkin_date:
        start, end = _day_bounds(q_checkin_date)
        if start and end:
            where.append("c.checkin_time>=%s AND c.checkin_time<=%s")
            params.extend([start, end])
    if name:
        where.append("(IFNULL(r.reserve_name, cu.name) LIKE %s OR cu.name LIKE %s)")
        params.extend([f"%{name}%", f"%{name}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY c.checkin_time DESC"
    cur.execute(sql, params)
    out = []
    for row in cur.fetchall():
        checkin_id, cust_id, room_id, room_type, price, checkin_time, operator, operator_user_id, actual_checkout_time, reserve_name, reserve_phone_enc = row
        try:
            reserve_phone = decrypt_phone(reserve_phone_enc) if reserve_phone_enc else ""
        except Exception:
            reserve_phone = ""
        customer_name = str(reserve_name or "").strip()
        if not customer_name:
            customer_name = str(_find_customer(str(cust_id))[1] or "")
        if name and name not in customer_name:
            continue
        if phone and reserve_phone != phone:
            continue
        final_operator = operator
        out.append((checkin_id, customer_name, mask_phone(reserve_phone) if reserve_phone else "", room_id, room_type, float(price) if price is not None else 0, checkin_time, final_operator, operator_user_id, actual_checkout_time))
    return out


def query_checkout_records(name="", phone="", checkout_date=None):
    ensure_checkin_checkout_columns()
    name = str(name or "").strip()
    phone = normalize_phone(phone)
    q_checkout_date = _parse_date_value(checkout_date)
    _, cur = _db()
    sql = (
        "SELECT co.checkout_id, co.cust_id, co.room_id, rm.room_type, rm.price, co.checkin_date, co.checkout_time, co.total_fee, co.extra_fee, co.operator, co.operator_user_id, "
        "IFNULL(r.reserve_name, cu.name), r.reserve_phone_encrypted "
        "FROM checkout co "
        "JOIN customer cu ON co.cust_id=cu.cust_id "
        "LEFT JOIN reservation r ON r.cust_id=co.cust_id AND r.room_id=co.room_id "
        "JOIN room rm ON co.room_id=rm.room_id "
    )
    where = []
    params = []
    if q_checkout_date:
        start, end = _day_bounds(q_checkout_date)
        if start and end:
            where.append("co.checkout_time>=%s AND co.checkout_time<=%s")
            params.extend([start, end])
    if name:
        where.append("(IFNULL(r.reserve_name, cu.name) LIKE %s OR cu.name LIKE %s)")
        params.extend([f"%{name}%", f"%{name}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY co.checkout_time DESC"
    cur.execute(sql, params)
    out = []
    for row in cur.fetchall():
        checkout_id, cust_id, room_id, room_type, price, row_checkin_date, checkout_time, total_fee, extra_fee, operator, operator_user_id, reserve_name, reserve_phone_enc = row
        try:
            reserve_phone = decrypt_phone(reserve_phone_enc) if reserve_phone_enc else ""
        except Exception:
            reserve_phone = ""
        customer_name = str(reserve_name or "").strip()
        if not customer_name:
            customer_name = str(_find_customer(str(cust_id))[1] or "")
        if name and name not in customer_name:
            continue
        if phone and reserve_phone != phone:
            continue
        if q_checkout_date and _parse_date_value(checkout_time) != q_checkout_date:
            continue
        checkout_day = _parse_date_value(checkout_time) or _parse_date_value(row_checkin_date)
        out.append((checkout_id, customer_name, mask_phone(reserve_phone) if reserve_phone else "", room_id, room_type, float(price) if price is not None else 0, checkout_day, checkout_time, float(total_fee) if total_fee is not None else 0, float(extra_fee) if extra_fee is not None else 0, operator, operator_user_id))
    return out


def add_maintenance(room_id, record_type, handler, result, remark, operator):
    conn, cur = _db()
    try:
        record_type = str(record_type or "").strip()
        if record_type not in {"维修", "清洁"}:
            return False, "记录类型无效"
        cur.execute(
            "INSERT INTO room_maintenance_clean(room_id,record_type,record_time,handler,result,remark) VALUES(%s,%s,%s,%s,%s,%s)",
            (room_id, record_type, datetime.now(), handler, result, remark or ""),
        )
        cur.execute("UPDATE room SET status=%s WHERE room_id=%s", (_maintenance_room_status(record_type), room_id))
        conn.commit()
        _log(operator, "维护记录", f"{room_id} {record_type}")
        return True, "记录添加成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def complete_maintenance(room_id, record_type):
    conn, cur = _db()
    try:
        cur.execute(
            "UPDATE room_maintenance_clean SET result='已完成' WHERE room_id=%s AND record_type=%s AND result!='已完成' ORDER BY record_time DESC LIMIT 1",
            (room_id, record_type),
        )
        _sync_room_status(cur, room_id)
        conn.commit()
        return (True, "已标记完成") if cur.rowcount else (False, "未找到可完成记录")
    except Exception as e:
        conn.rollback()
        return False, str(e)


def advanced_room_query(room_id, room_type, status, area_min, area_max, price_min, price_max, checkin_date=None, checkout_date=None, customer_name=None, customer_phone=None, checkin_time=None):
    where, params = [], []
    if room_id:
        where.append("room_id=%s"); params.append(room_id)
    if room_type:
        where.append("room_type=%s"); params.append(room_type)
    if status:
        where.append("status=%s"); params.append(status)
    if area_min not in (None, ""):
        where.append("area>=%s"); params.append(float(area_min))
    if area_max not in (None, ""):
        where.append("area<=%s"); params.append(float(area_max))
    if price_min not in (None, ""):
        where.append("price>=%s"); params.append(float(price_min))
    if price_max not in (None, ""):
        where.append("price<=%s"); params.append(float(price_max))
    sql = "SELECT room_id, room_type, area, price, status FROM room"
    if where:
        sql += " WHERE " + " AND ".join(where)
    _, cur = _db()
    cur.execute(sql, params)
    rows = cur.fetchall()
    q_checkin = _parse_date_value(checkin_date)
    q_checkout = _parse_date_value(checkout_date)
    q_active_checkin = _parse_date_value(checkin_time)
    active_rows = {row["room_id"]: row for row in _active_stay_rows(cur)}
    occupied_room_ids = set(active_rows.keys())
    reserved_room_ids = set()
    if q_checkin and q_checkout:
        cur.execute(
            "SELECT DISTINCT room_id FROM reservation "
            "WHERE status IN (%s,%s) "
            "AND checkin_date IS NOT NULL AND checkout_date IS NOT NULL "
            "AND checkin_date < %s AND checkout_date > %s",
            (ROOM_STATUS_RESERVED, ROOM_STATUS_OCCUPIED, q_checkout, q_checkin),
        )
        reserved_room_ids = {row[0] for row in cur.fetchall()}
    out = []
    for row in rows:
        rid, rtype, area, price, room_status = row
        final_status = normalize_status(room_status)
        if rid in occupied_room_ids:
            final_status = ROOM_STATUS_OCCUPIED
        elif rid in reserved_room_ids:
            final_status = ROOM_STATUS_RESERVED
        if status and normalize_status(status) == ROOM_STATUS_FREE and final_status != ROOM_STATUS_FREE:
            continue
        active = active_rows.get(rid)
        if customer_name or customer_phone or q_active_checkin:
            if not active:
                continue
            if customer_name and customer_name not in str(active["customer"] or ""):
                continue
            if customer_phone and normalize_phone(customer_phone) != normalize_phone(active["phone"]):
                continue
            if q_active_checkin and _parse_date_value(active["checkin_time"]) != q_active_checkin:
                continue
        out.append((
            rid,
            rtype,
            area,
            price,
            final_status,
            active["res_id"] if active else None,
            active["customer"] if active else "",
            mask_phone(active["phone"]) if active and active["phone"] else "",
            active["checkin_time"] if active else None,
            active["checkout_date"] if active else None,
            active["operator"] if active else "",
        ))
    return out


def get_checkin_records():
    return query_checkin_records()


def get_checkout_records():
    return query_checkout_records()


def get_income_records():
    return query_income_records()


def search_active_stays(keyword, customer_name=None, phone=None, checkin_date=None):
    ensure_reservation_columns()
    kw = str(keyword or "").strip()
    query_phone = normalize_phone(phone) or normalize_phone(kw)
    query_name = str(customer_name or "").strip()
    q_checkin_date = _parse_date_value(checkin_date)
    active_rows = _active_stay_rows()
    out = []
    for active in active_rows:
        haystack = " ".join(str(x or "") for x in [
            active["checkin_id"],
            active["res_id"],
            active["room_id"],
            active["customer"],
            active["room_type"],
            active["checkin_time"],
            active["checkout_date"],
            active["operator"],
            active["res_status"],
            active["phone"],
        ])
        if kw and kw not in haystack and kw not in str(active["phone"]):
            continue
        if query_name and query_name not in str(active["customer"] or ""):
            continue
        if query_phone and query_phone != normalize_phone(active["phone"]):
            continue
        if q_checkin_date and _parse_date_value(active["checkin_time"]) != q_checkin_date:
            continue
        out.append((
            active["checkin_id"],
            active["res_id"],
            active["customer"],
            active["phone"],
            active["room_id"],
            active["room_type"],
            active["price"],
            active["checkin_time"],
            active["checkout_date"],
            active["res_status"],
        ))
    return out


def get_reservation_records():
    return query_reservation_records()
def get_statistics(year_month):
    _, cur = _db()
    start, end = _month_bounds(year_month)
    if not start or not end:
        return 0.0, 0.0, "无"
    cur.execute("SELECT IFNULL(SUM(total_fee),0) FROM checkout WHERE checkout_time>=%s AND checkout_time<%s", (start, end))
    income = float(cur.fetchone()[0] or 0)
    cur.execute("SELECT COUNT(*) FROM room")
    room_count = cur.fetchone()[0]
    y, m = map(int, year_month.split("-"))
    days = calendar.monthrange(y, m)[1]
    cur.execute("SELECT COUNT(*) FROM checkin WHERE checkin_time>=%s AND checkin_time<%s", (start, end))
    checkins = cur.fetchone()[0]
    occupancy = (checkins / (room_count * days) * 100) if room_count and days else 0
    cur.execute(
        "SELECT r.room_type, COUNT(*) c FROM checkin c JOIN room r ON c.room_id=r.room_id "
        "WHERE c.checkin_time>=%s AND c.checkin_time<%s GROUP BY r.room_type ORDER BY c DESC LIMIT 1",
        (start, end),
    )
    row = cur.fetchone()
    return income, occupancy, (row[0] if row else "无")


def get_customer_history(keyword):
    cid, _ = _find_customer(keyword)
    if not cid:
        return []
    _, cur = _db()
    cur.execute(
        "SELECT c.checkin_id, c.room_id, c.checkin_time, c.actual_checkout_time, co.total_fee "
        "FROM checkin c LEFT JOIN checkout co ON c.room_id=co.room_id AND c.cust_id=co.cust_id "
        "WHERE c.cust_id=%s ORDER BY c.checkin_time DESC",
        (cid,),
    )
    return cur.fetchall()


def get_customer_orders(name, phone, account_nickname=None):
    p = normalize_phone(phone)
    if not p:
        return []
    account_nickname = str(account_nickname or "").strip()
    _, cur = _db()
    cur.execute("SELECT cust_id, name, phone_encrypted FROM customer WHERE phone_encrypted IS NOT NULL")
    target_cid = None
    for cid, cname, enc in cur.fetchall():
        try:
            if decrypt_phone(enc) == p:
                if name and str(cname) != str(name):
                    # same phone but different display name: still accept phone as source of truth
                    pass
                target_cid = cid
                break
        except Exception:
            continue
    if not target_cid:
        return []
    cur.execute(
        "SELECT r.res_id, r.room_id, rm.room_type, rm.price, r.checkin_date, r.checkout_date, r.status, "
        "IFNULL(r.reserve_name, c.name) AS reserve_name, r.reserve_phone_encrypted "
        ", IFNULL(r.account_nickname, '') AS account_nickname "
        "FROM reservation r "
        "JOIN room rm ON r.room_id=rm.room_id "
        "JOIN customer c ON r.cust_id=c.cust_id "
        "WHERE r.cust_id=%s ORDER BY r.res_id DESC",
        (target_cid,),
    )
    out = []
    for row in cur.fetchall():
        row = list(row)
        if account_nickname and str(row[9] or "").strip() != account_nickname:
            continue
        try:
            row[8] = mask_phone(decrypt_phone(row[8])) if row[8] else ""
        except Exception:
            row[8] = "*** **** ****"
        out.append(tuple(row))
    return out


def search_reservation_orders(name, phone):
    name = str(name or "").strip()
    p = normalize_phone(phone)
    if not name and not p:
        return []
    ensure_reservation_columns()
    _, cur = _db()
    sql = (
        "SELECT r.res_id, r.room_id, rm.room_type, rm.price, r.checkin_date, r.checkout_date, r.status, "
        "IFNULL(r.reserve_name, c.name) AS reserve_name, r.reserve_phone_encrypted, "
        "IFNULL(r.account_nickname, '') AS account_nickname, c.name AS customer_name "
        "FROM reservation r "
        "JOIN room rm ON r.room_id=rm.room_id "
        "JOIN customer c ON r.cust_id=c.cust_id "
    )
    where = []
    params = []
    if name:
        where.append("(IFNULL(r.reserve_name, c.name) LIKE %s OR c.name LIKE %s)")
        params.extend([f"%{name}%", f"%{name}%"])
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY r.res_id DESC"
    cur.execute(sql, params)
    out = []
    for row in cur.fetchall():
        row = list(row)
        reserve_name = str(row[7] or "").strip()
        customer_name = str(row[10] or "").strip()
        try:
            reserve_phone = decrypt_phone(row[8]) if row[8] else ""
        except Exception:
            reserve_phone = ""
        matched = False
        if name and (name in reserve_name or name in customer_name):
            matched = True
        if p and reserve_phone == p:
            matched = True
        if not matched:
            continue
        row[8] = mask_phone(reserve_phone) if reserve_phone else ""
        out.append(tuple(row[:10]))
    return out


def get_customer_orders_by_cust_id(cust_id, account_nickname=None):
    try:
        cid = int(cust_id)
    except Exception:
        return []
    account_nickname = str(account_nickname or "").strip()
    _, cur = _db()
    cur.execute(
        "SELECT r.res_id, r.room_id, rm.room_type, rm.price, r.checkin_date, r.checkout_date, r.status, "
        "IFNULL(r.reserve_name, c.name) AS reserve_name, r.reserve_phone_encrypted "
        ", IFNULL(r.account_nickname, '') AS account_nickname "
        "FROM reservation r "
        "JOIN room rm ON r.room_id=rm.room_id "
        "JOIN customer c ON r.cust_id=c.cust_id "
        "WHERE r.cust_id=%s ORDER BY r.res_id DESC",
        (cid,),
    )
    out = []
    for row in cur.fetchall():
        row = list(row)
        if account_nickname and str(row[9] or "").strip() != account_nickname:
            continue
        try:
            row[8] = mask_phone(decrypt_phone(row[8])) if row[8] else ""
        except Exception:
            row[8] = "*** **** ****"
        out.append(tuple(row))
    return out


def get_monthly_series(months):
    out = []
    for ym in months:
        income, occ, hot = get_statistics(ym)
        out.append({"month": ym, "income": income, "occupancy_rate": occ, "hot_type": hot})
    return out


def submit_complaint(checkout_id, room_id, customer_name, score, comment):
    conn, cur = _db()
    cur.execute(
        "INSERT INTO complaint(checkout_id, room_id, customer_name, score, comment, status) VALUES(%s,%s,%s,%s,%s,'未处理')",
        (checkout_id, room_id, customer_name, score, comment),
    )
    conn.commit()
    return True


def add_service_request(request_type, customer_name, customer_phone, room_id=None, target_room_id=None, score=None, content=""):
    phone = normalize_phone(customer_phone)
    if not phone:
        return False, "手机号必须为11位数字"
    ensure_service_request_table()
    conn, cur = _db()
    cur.execute(
        "INSERT INTO service_request(request_type, customer_name, customer_phone, room_id, target_room_id, score, content, status, created_at) "
        "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        (request_type, customer_name, encrypt_phone(phone), room_id, target_room_id, score, content, REQUEST_STATUS_PENDING, datetime.now()),
    )
    conn.commit()
    if score is not None and int(score) < 2:
        try:
            conn2, cur2 = _db()
            cur2.execute("SELECT checkout_id FROM checkout WHERE room_id=%s ORDER BY checkout_time DESC LIMIT 1", (room_id,))
            row = cur2.fetchone()
            if row and row[0]:
                submit_complaint(row[0], room_id, customer_name, int(score), content)
        except Exception:
            pass
    return True, "提交成功"


def list_service_requests():
    ensure_service_request_table()
    _, cur = _db()
    cur.execute(
        "SELECT request_id, request_type, customer_name, customer_phone, room_id, target_room_id, score, content, status, "
        "handler, response, created_at, handled_at FROM service_request ORDER BY created_at DESC LIMIT 500"
    )
    out = []
    for row in cur.fetchall():
        row = list(row)
        try:
            row[3] = mask_phone(decrypt_phone(row[3]))
        except Exception:
            row[3] = "*** **** ****"
        out.append(tuple(row))
    return out


def get_service_request_by_id(request_id):
    ensure_service_request_table()
    _, cur = _db()
    cur.execute(
        "SELECT request_id, request_type, customer_name, customer_phone, room_id, target_room_id, score, content, status "
        "FROM service_request WHERE request_id=%s",
        (request_id,),
    )
    row = cur.fetchone()
    if not row:
        return None
    row = list(row)
    try:
        row[3] = decrypt_phone(row[3])
    except Exception:
        row[3] = ""
    return tuple(row)


def handle_service_request(request_id, handler, response):
    ensure_service_request_table()
    conn, cur = _db()
    cur.execute(
        "UPDATE service_request SET status=%s, handler=%s, response=%s, handled_at=%s WHERE request_id=%s AND status=%s",
        (REQUEST_STATUS_DONE, handler, response, datetime.now(), request_id, REQUEST_STATUS_PENDING),
    )
    conn.commit()
    return cur.rowcount > 0


def reject_service_request(request_id, handler, response):
    ensure_service_request_table()
    conn, cur = _db()
    cur.execute(
        "UPDATE service_request SET status=%s, handler=%s, response=%s, handled_at=%s WHERE request_id=%s AND status=%s",
        (REQUEST_STATUS_REJECTED, handler, response, datetime.now(), request_id, REQUEST_STATUS_PENDING),
    )
    conn.commit()
    return cur.rowcount > 0


def get_all_employees():
    ensure_user_role_enum()
    _, cur = _db()
    cur.execute("SELECT user_id, username, role, created_at FROM users ORDER BY user_id")
    return cur.fetchall()


def get_operation_logs():
    _, cur = _db()
    cur.execute("SELECT operator, operation_type, detail, log_time FROM operation_log ORDER BY log_time DESC LIMIT 200")
    rows = cur.fetchall()
    return [
        (operator, _format_operation_detail(operation_type, operation_type), _format_operation_detail(operation_type, detail), log_time)
        for operator, operation_type, detail, log_time in rows
    ]


def add_new_user(username, password, role):
    ensure_user_role_enum()
    if role not in {"manager", "receptionist", "frontdesk"}:
        return False, "客户不在 users 表维护"
    conn, cur = _db()
    try:
        cur.execute("INSERT INTO users(username,password,role) VALUES(%s,%s,%s)", (username, password, role))
        conn.commit()
        return True, "新增成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def update_user_info(user_id, new_username, new_role):
    ensure_user_role_enum()
    if new_role not in {"manager", "receptionist", "frontdesk"}:
        return False, "客户不在 users 表维护"
    conn, cur = _db()
    try:
        cur.execute("UPDATE users SET username=%s, role=%s WHERE user_id=%s", (new_username, new_role, user_id))
        conn.commit()
        return True, "修改成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def delete_user(user_id):
    conn, cur = _db()
    try:
        cur.execute("DELETE FROM users WHERE user_id=%s", (user_id,))
        conn.commit()
        return True, "删除成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def get_room_types():
    _, cur = _db()
    try:
        cur.execute("SELECT type_name, base_price FROM room_type ORDER BY type_name")
        return cur.fetchall()
    except Exception:
        cur.execute("SELECT DISTINCT room_type, MIN(price) FROM room GROUP BY room_type ORDER BY room_type")
        return cur.fetchall()


def add_room_type(name, price, operator=None):
    conn, cur = _db()
    try:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS room_type (
                type_id INT AUTO_INCREMENT PRIMARY KEY,
                type_name VARCHAR(50) UNIQUE NOT NULL,
                base_price DECIMAL(10,2) NOT NULL
            )
            """
        )
        cur.execute(
            "INSERT INTO room_type(type_name, base_price) VALUES(%s, %s) "
            "ON DUPLICATE KEY UPDATE base_price=VALUES(base_price)",
            (name, float(price)),
        )
        conn.commit()
        if operator:
            _log(operator, "房型管理", f"{name}={price}")
        return True, "房型保存成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def update_room_price(room_id, new_price, operator, role):
    if role != "manager":
        return False, "权限不足"
    conn, cur = _db()
    cur.execute("UPDATE room SET price=%s WHERE room_id=%s", (float(new_price), room_id))
    conn.commit()
    _log(operator, "改价", f"房间{room_id}改价{new_price}")
    return True, "修改成功"


def add_new_room(room_id, room_type, area, price, operator, role):
    if role != "manager":
        return False, "权限不足"
    conn, cur = _db()
    try:
        cur.execute(
            "INSERT INTO room(room_id,room_type,area,price,status) VALUES(%s,%s,%s,%s,%s)",
            (room_id, room_type, area, price, ROOM_STATUS_FREE),
        )
        conn.commit()
        _log(operator, "新增客房", f"新增房间{room_id}")
        return True, "新增成功"
    except Exception as e:
        conn.rollback()
        return False, str(e)


def batch_update_rooms(room_id_from, room_id_to, new_price, new_status, operator, role):
    if role != "manager":
        return False, "权限不足"
    conn, cur = _db()
    updates = []
    if new_price not in (None, ""):
        cur.execute("UPDATE room SET price=%s WHERE room_id BETWEEN %s AND %s", (float(new_price), int(room_id_from), int(room_id_to)))
        updates.append(f"价格={new_price}")
    if new_status:
        cur.execute("UPDATE room SET status=%s WHERE room_id BETWEEN %s AND %s", (new_status, int(room_id_from), int(room_id_to)))
        updates.append(f"状态={new_status}")
    if not updates:
        return False, "没有修改内容"
    conn.commit()
    _log(operator, "批量修改客房", f"{room_id_from}-{room_id_to} {';'.join(updates)}")
    return True, "批量修改成功"


def update_room_info(room_id, room_type, area, price, status, operator, role):
    if role != "manager":
        return False, "权限不足"
    if not room_id:
        return False, "房间号不能为空"
    conn, cur = _db()
    try:
        cur.execute("SELECT room_id FROM room WHERE room_id=%s", (room_id,))
        if not cur.fetchone():
            return False, "房间不存在"

        updates = []
        params = []
        if room_type not in (None, ""):
            updates.append("room_type=%s")
            params.append(str(room_type).strip())
        if area not in (None, ""):
            updates.append("area=%s")
            params.append(float(area))
        if price not in (None, ""):
            updates.append("price=%s")
            params.append(float(price))
        if status not in (None, ""):
            updates.append("status=%s")
            params.append(normalize_status(status))
        if not updates:
            return False, "没有修改内容"

        params.append(int(room_id))
        cur.execute(f"UPDATE room SET {', '.join(updates)} WHERE room_id=%s", params)
        conn.commit()
        _log(operator, "房间编辑", f"房间{room_id}信息更新")
        return True, "房间信息已更新"
    except Exception as e:
        conn.rollback()
        return False, str(e)

