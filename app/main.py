import calendar
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from functools import wraps
from io import BytesIO

from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from werkzeug.security import check_password_hash, generate_password_hash


WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]
MONTHS = [
    "Januar",
    "Februar",
    "März",
    "April",
    "Mai",
    "Juni",
    "Juli",
    "August",
    "September",
    "Oktober",
    "November",
    "Dezember",
]


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-change-me")
    app.config["DATABASE_PATH"] = os.environ.get("DATABASE_PATH", "data/bereitschaft.sqlite")
    os.makedirs(os.path.dirname(app.config["DATABASE_PATH"]), exist_ok=True)

    init_db(app)

    @app.get("/")
    @login_required
    def index():
        user = current_user()
        year = int(request.args.get("year", datetime.now().year))
        month = int(request.args.get("month", datetime.now().month))
        data = month_data(user["id"], year, month)
        types = query_all("SELECT * FROM readiness_types WHERE active = 1 ORDER BY name")
        return render_template("index.html", user=user, year=year, month=month, months=MONTHS, data=data, types=types)

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = query_one("SELECT * FROM users WHERE username = ?", (username,))
            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                return redirect(url_for("index"))
            flash("Login fehlgeschlagen.", "error")
        return render_template("login.html")

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/profile", methods=["GET", "POST"])
    @login_required
    def profile():
        user = current_user()
        if request.method == "POST":
            execute(
                "UPDATE users SET personnel_no = ?, first_name = ?, last_name = ? WHERE id = ?",
                (
                    request.form.get("personnel_no", "").strip(),
                    request.form.get("first_name", "").strip(),
                    request.form.get("last_name", "").strip(),
                    user["id"],
                ),
            )
            flash("Stammdaten gespeichert.", "success")
            return redirect(url_for("profile"))
        return render_template("profile.html", user=current_user())

    @app.route("/readiness", methods=["POST"])
    @login_required
    def add_readiness():
        user = current_user()
        start_date = date_from_month_form("start_day")
        end_date = date_from_month_form("end_day")
        if end_date < start_date:
            flash("Ende darf nicht vor Beginn liegen.", "error")
            return month_redirect()
        execute(
            """
            INSERT INTO readiness (user_id, readiness_type_id, start_date, end_date, kind, start_time, end_time, hours_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                int(request.form["readiness_type_id"]),
                start_date.isoformat(),
                end_date.isoformat(),
                readiness_type_name(int(request.form["readiness_type_id"])),
                "00:00",
                "00:00",
                0,
            ),
        )
        flash("Bereitschaft gespeichert.", "success")
        return month_redirect(start_date.year, start_date.month)

    @app.post("/readiness/<int:item_id>/delete")
    @login_required
    def delete_readiness(item_id):
        execute("DELETE FROM readiness WHERE id = ? AND user_id = ?", (item_id, current_user()["id"]))
        return month_redirect()

    @app.route("/work", methods=["POST"])
    @login_required
    def add_work():
        user = current_user()
        work_date = date_from_month_form("work_day")
        execute(
            """
            INSERT INTO work_entries (user_id, work_date, start_time, end_time, note, compensation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                work_date.isoformat(),
                request.form["start_time"],
                request.form["end_time"],
                request.form.get("note", "").strip(),
                request.form.get("compensation", "Freizeit"),
            ),
        )
        flash("Einsatz gespeichert.", "success")
        return month_redirect(work_date.year, work_date.month)

    @app.post("/work/<int:item_id>/delete")
    @login_required
    def delete_work(item_id):
        execute("DELETE FROM work_entries WHERE id = ? AND user_id = ?", (item_id, current_user()["id"]))
        return month_redirect()

    @app.get("/pdf/<int:year>/<int:month>")
    @login_required
    def pdf(year, month):
        if month < 1 or month > 12:
            abort(404)
        user = current_user()
        buffer = BytesIO()
        render_month_pdf(buffer, user, month_data(user["id"], year, month), year, month)
        buffer.seek(0)
        filename = f"rufbereitschaft_{year}_{month:02d}_{user['username']}.pdf"
        return send_file(buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)

    @app.get("/print/<int:year>/<int:month>")
    @login_required
    def print_month(year, month):
        if month < 1 or month > 12:
            abort(404)
        user = current_user()
        data = month_data(user["id"], year, month)
        return render_template("print_month.html", user=user, data=data, year=year, month=month, months=MONTHS)

    @app.route("/admin/users", methods=["GET", "POST"])
    @admin_required
    def admin_users():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not username or not password:
                flash("Benutzername und Passwort sind Pflicht.", "error")
            else:
                try:
                    execute(
                        """
                        INSERT INTO users (username, password_hash, role, personnel_no, first_name, last_name)
                        VALUES (?, ?, 'user', ?, ?, ?)
                        """,
                        (
                            username,
                            generate_password_hash(password),
                            request.form.get("personnel_no", "").strip(),
                            request.form.get("first_name", "").strip(),
                            request.form.get("last_name", "").strip(),
                        ),
                    )
                    flash("Benutzer angelegt.", "success")
                except sqlite3.IntegrityError:
                    flash("Benutzername existiert bereits.", "error")
        users = query_all("SELECT id, username, role, personnel_no, first_name, last_name FROM users ORDER BY username")
        return render_template("admin_users.html", user=current_user(), users=users)

    @app.route("/admin/types", methods=["GET", "POST"])
    @admin_required
    def admin_types():
        if request.method == "POST":
            type_id = request.form.get("type_id")
            values = (
                request.form.get("name", "").strip(),
                request.form.get("weekday_start", ""),
                request.form.get("weekday_end", ""),
                request.form.get("friday_start", ""),
                request.form.get("friday_end", ""),
                request.form.get("weekend_start", ""),
                request.form.get("weekend_end", ""),
                request.form.get("holiday_start", ""),
                request.form.get("holiday_end", ""),
            )
            if not values[0]:
                flash("Name ist Pflicht.", "error")
            elif type_id:
                execute(
                    """
                    UPDATE readiness_types
                    SET name = ?, weekday_start = ?, weekday_end = ?, friday_start = ?, friday_end = ?,
                        weekend_start = ?, weekend_end = ?, holiday_start = ?, holiday_end = ?
                    WHERE id = ?
                    """,
                    (*values, int(type_id)),
                )
                flash("Bereitschaftsart gespeichert.", "success")
            else:
                execute(
                    """
                    INSERT INTO readiness_types
                    (name, weekday_start, weekday_end, friday_start, friday_end, weekend_start, weekend_end, holiday_start, holiday_end)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    values,
                )
                flash("Bereitschaftsart angelegt.", "success")
        types = query_all("SELECT * FROM readiness_types ORDER BY name")
        return render_template("admin_types.html", user=current_user(), types=types)

    @app.post("/admin/types/<int:type_id>/toggle")
    @admin_required
    def toggle_type(type_id):
        execute("UPDATE readiness_types SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (type_id,))
        return redirect(url_for("admin_types"))

    return app


def get_db():
    app = Flask.current_app if False else None
    from flask import current_app, g

    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE_PATH"])
        g.db.row_factory = sqlite3.Row
    return g.db


def init_db(app):
    with app.app_context():
        with closing(sqlite3.connect(app.config["DATABASE_PATH"])) as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT NOT NULL UNIQUE,
                    password_hash TEXT NOT NULL,
                    role TEXT NOT NULL DEFAULT 'user',
                    personnel_no TEXT DEFAULT '',
                    first_name TEXT DEFAULT '',
                    last_name TEXT DEFAULT ''
                );

                CREATE TABLE IF NOT EXISTS readiness (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    readiness_type_id INTEGER REFERENCES readiness_types(id),
                    start_date TEXT NOT NULL,
                    end_date TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    hours_per_day REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS work_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    work_date TEXT NOT NULL,
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    compensation TEXT NOT NULL DEFAULT 'Freizeit'
                );

                CREATE TABLE IF NOT EXISTS readiness_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    weekday_start TEXT NOT NULL DEFAULT '',
                    weekday_end TEXT NOT NULL DEFAULT '',
                    friday_start TEXT NOT NULL DEFAULT '',
                    friday_end TEXT NOT NULL DEFAULT '',
                    weekend_start TEXT NOT NULL DEFAULT '',
                    weekend_end TEXT NOT NULL DEFAULT '',
                    holiday_start TEXT NOT NULL DEFAULT '',
                    holiday_end TEXT NOT NULL DEFAULT '',
                    active INTEGER NOT NULL DEFAULT 1
                );
                """
            )
            ensure_column(db, "readiness", "readiness_type_id", "INTEGER REFERENCES readiness_types(id)")
            seed_default_type(db)
            admin = db.execute("SELECT id FROM users WHERE username = 'admin'").fetchone()
            if admin is None:
                db.execute(
                    """
                    INSERT INTO users (username, password_hash, role, personnel_no, first_name, last_name)
                    VALUES ('admin', ?, 'admin', '', 'Admin', '')
                    """,
                    (generate_password_hash(os.environ.get("ADMIN_PASSWORD", "admin123")),),
                )
            db.commit()


def ensure_column(db, table, column, definition):
    columns = [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_default_type(db):
    existing = db.execute("SELECT id FROM readiness_types LIMIT 1").fetchone()
    if existing is None:
        db.execute(
            """
            INSERT INTO readiness_types
            (name, weekday_start, weekday_end, friday_start, friday_end, weekend_start, weekend_end, holiday_start, holiday_end)
            VALUES ('Bereitschaft', '12:15', '18:00', '12:15', '18:00', '06:00', '18:00', '06:00', '18:00')
            """
        )
    default_type = db.execute("SELECT id FROM readiness_types ORDER BY id LIMIT 1").fetchone()
    if default_type is not None:
        db.execute("UPDATE readiness SET readiness_type_id = ? WHERE readiness_type_id IS NULL", (default_type[0],))


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def execute(sql, params=()):
    db = get_db()
    db.execute(sql, params)
    db.commit()


def readiness_type_name(type_id):
    row = query_one("SELECT name FROM readiness_types WHERE id = ?", (type_id,))
    return row["name"] if row else "Bereitschaft"


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if current_user() is None:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def parse_date(value):
    return datetime.strptime(value, "%Y-%m-%d").date()


def decimal_hours(start_value, end_value):
    if not start_value or not end_value:
        return 0
    start = datetime.strptime(start_value, "%H:%M").time()
    end = datetime.strptime(end_value, "%H:%M").time()
    return round(((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) / 60, 2)


def daterange(start, end):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def easter_sunday(year):
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(year, month, day)


def holidays_for_year(year):
    easter = easter_sunday(year)
    return {
        date(year, 1, 1),
        easter - timedelta(days=2),
        easter + timedelta(days=1),
        date(year, 5, 1),
        easter + timedelta(days=39),
        easter + timedelta(days=50),
        easter + timedelta(days=60),
        date(year, 10, 3),
        date(year, 11, 1),
        date(year, 12, 25),
        date(year, 12, 26),
    }


def is_holiday(day):
    return day in holidays_for_year(day.year)


def rule_for_day(readiness_type, day):
    if is_holiday(day):
        start, end = readiness_type["holiday_start"], readiness_type["holiday_end"]
    elif day.weekday() == 4:
        start, end = readiness_type["friday_start"], readiness_type["friday_end"]
    elif day.weekday() >= 5:
        start, end = readiness_type["weekend_start"], readiness_type["weekend_end"]
    else:
        start, end = readiness_type["weekday_start"], readiness_type["weekday_end"]
    if not start or not end:
        return None
    return {"start_time": start, "end_time": end, "hours": decimal_hours(start, end)}


def month_redirect_from_form(date_field="start_date"):
    d = parse_date(request.form[date_field])
    return redirect(url_for("index", year=d.year, month=d.month))


def month_redirect(year=None, month=None):
    return redirect(url_for("index", year=year or request.form.get("year"), month=month or request.form.get("month")))


def date_from_month_form(day_field):
    year = int(request.form["year"])
    month = int(request.form["month"])
    day = int(request.form[day_field])
    max_day = calendar.monthrange(year, month)[1]
    if day < 1 or day > max_day:
        abort(400)
    return date(year, month, day)


def month_data(user_id, year, month):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    readiness = query_all(
        """
        SELECT r.*, t.name AS type_name, t.weekday_start, t.weekday_end, t.friday_start, t.friday_end,
               t.weekend_start, t.weekend_end, t.holiday_start, t.holiday_end
        FROM readiness r
        LEFT JOIN readiness_types t ON t.id = r.readiness_type_id
        WHERE r.user_id = ? AND r.start_date <= ? AND r.end_date >= ?
        ORDER BY r.start_date, r.id
        """,
        (user_id, last.isoformat(), first.isoformat()),
    )
    work_entries = query_all(
        """
        SELECT * FROM work_entries
        WHERE user_id = ? AND work_date BETWEEN ? AND ?
        ORDER BY work_date, start_time
        """,
        (user_id, first.isoformat(), last.isoformat()),
    )

    readiness_display = []
    for item in readiness:
        item_start = max(parse_date(item["start_date"]), first)
        item_end = min(parse_date(item["end_date"]), last)
        for current in daterange(item_start, item_end):
            rule = rule_for_day(item, current)
            if rule:
                readiness_display.append(
                    {
                        "id": item["id"],
                        "kind": item["type_name"] or item["kind"],
                        "start_date": current.isoformat(),
                        "end_date": current.isoformat(),
                        "start_time": rule["start_time"],
                        "end_time": rule["end_time"],
                    }
                )

    days = []
    for day in range(1, last.day + 1):
        current = date(year, month, day)
        day_readiness = []
        for r in readiness:
            if parse_date(r["start_date"]) <= current <= parse_date(r["end_date"]):
                rule = rule_for_day(r, current)
                if rule:
                    day_readiness.append(
                        {
                            "id": r["id"],
                            "kind": r["type_name"] or r["kind"],
                            "start_time": rule["start_time"],
                            "end_time": rule["end_time"],
                            "hours_per_day": rule["hours"],
                        }
                    )
        entries = []
        for w in work_entries:
            if w["work_date"] == current.isoformat():
                entries.append(
                    {
                        "id": w["id"],
                        "work_date": w["work_date"],
                        "start_time": w["start_time"],
                        "end_time": w["end_time"],
                        "note": w["note"],
                        "compensation": w["compensation"],
                        "hours": decimal_hours(w["start_time"], w["end_time"]),
                    }
                )
        soll = sum(float(r["hours_per_day"]) for r in day_readiness)
        more = sum(w["hours"] for w in entries)
        days.append(
            {
                "date": current,
                "weekday": WEEKDAYS[current.weekday()],
                "holiday": is_holiday(current),
                "readiness": day_readiness,
                "entries": entries,
                "soll": round(soll, 2),
                "mehrarbeit": round(more, 2),
                "ist": round(soll - more, 2),
            }
        )

    return {
        "readiness": readiness_display,
        "work_entries": work_entries,
        "days": days,
        "sum_soll": round(sum(d["soll"] for d in days), 2),
        "sum_work": round(sum(d["mehrarbeit"] for d in days), 2),
        "sum_weekday": round(sum(d["ist"] for d in days if d["date"].weekday() < 5 and not d["holiday"]), 2),
        "sum_weekend": round(sum(d["ist"] for d in days if d["date"].weekday() >= 5 or d["holiday"]), 2),
    }


def draw_text(c, x, y, text, size=8, bold=False, align="left"):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


def fmt_hours(value):
    if value in ("", None):
        return ""
    return f"{float(value):.2f}".replace(".", ",")


def render_month_pdf(buffer, user, data, year, month):
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 12 * mm
    top = height - 22 * mm
    top_row_h = 5.0 * mm
    detail_row_h = 3.75 * mm

    draw_text(c, left, top, "Rufbereitschaft", 11, True)
    c.line(left, top - 1, left + 28 * mm, top - 1)
    draw_text(c, width - 62 * mm, top, "Monat:", 8, True)
    draw_text(c, width - 28 * mm, top, f"{MONTHS[month-1][:3]} {str(year)[2:]}", 8, True)

    draw_text(c, left, top - 18 * mm, "Pers.-Nr.:", 8, True)
    draw_text(c, left + 32 * mm, top - 18 * mm, user["personnel_no"] or "", 8, True)
    draw_text(c, left, top - 32 * mm, "Vorname:", 8, True)
    draw_text(c, left + 32 * mm, top - 32 * mm, user["first_name"] or "", 8, True)
    draw_text(c, left, top - 39 * mm, "Name:", 8, True)
    draw_text(c, left + 32 * mm, top - 39 * mm, user["last_name"] or "", 8, True)

    table_x = 78 * mm
    table_y = top - 12 * mm
    cols = [36, 24, 22, 20, 20]
    headers = ["", "Datum Beginn", "Datum Ende", "Uhrzeit von", "Uhrzeit bis"]
    for i, header in enumerate(headers):
        x = table_x + sum(cols[:i]) * mm
        c.rect(x, table_y - top_row_h, cols[i] * mm, top_row_h)
        draw_text(c, x + cols[i] * mm / 2, table_y - 3.6 * mm, header, 6.4, True, "center")
    for row_idx in range(7):
        y = table_y - (row_idx + 2) * top_row_h
        item = data["readiness"][row_idx] if row_idx < len(data["readiness"]) else None
        values = ["", "", "", "", ""]
        if item:
            values = [
                item["kind"],
                parse_date(item["start_date"]).strftime("%d.%m.%Y"),
                parse_date(item["end_date"]).strftime("%d.%m.%Y"),
                item["start_time"],
                item["end_time"],
            ]
        for i, val in enumerate(values):
            x = table_x + sum(cols[:i]) * mm
            c.rect(x, y, cols[i] * mm, top_row_h)
            draw_text(c, x + 1 * mm, y + 1.5 * mm, val, 5.9)

    grid_x = left
    grid_y = top - 70 * mm
    col_widths = [9, 11, 13, 12, 12, 13, 36, 20, 18, 19, 16]
    headers = ["Tag", "", "Soll-Ruf-\nbereit-\nschaft", "von", "bis", "Std.", "Bemerkung", "Bezahlen\nx", "Freizeit\nx", "Ist-Rufbereit-\nschaft", "Erschwernis-\nzuschlag\nStd."]
    x = grid_x
    header_h = 14 * mm
    for idx, header in enumerate(headers):
        c.rect(x, grid_y, col_widths[idx] * mm, header_h)
        for line_no, line in enumerate(header.split("\n")):
            draw_text(c, x + col_widths[idx] * mm / 2, grid_y + header_h - (line_no + 1) * 3.6 * mm, line, 5.8, True, "center")
        x += col_widths[idx] * mm

    y = grid_y - detail_row_h
    detail_rows = []
    for day in data["days"]:
        entries = list(day["entries"])
        detail_rows.append((day, entries[0] if entries else None, True, len(entries)))
        for extra in entries[1:]:
            detail_rows.append((day, extra, False, len(entries)))
    detail_rows = detail_rows[:36]
    red = colors.Color(0.82, 0.42, 0.42, alpha=0.65)
    for day, entry, first_row, entry_count in detail_rows:
        is_weekend = day["date"].weekday() >= 5 or day.get("holiday")
        if is_weekend:
            c.setFillColor(red)
            c.rect(grid_x, y, sum(col_widths) * mm, detail_row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)
        x = grid_x
        vals = [
            day["weekday"] if first_row else "",
            f"{day['date'].day}." if first_row else "",
            fmt_hours(day["soll"]) if first_row and day["soll"] else "",
            entry["start_time"] if entry else "",
            entry["end_time"] if entry else "",
            fmt_hours(decimal_hours(entry["start_time"], entry["end_time"])) if entry else "0,00",
            entry["note"] if entry else "",
            "x" if entry and entry["compensation"] == "Bezahlen" else "",
            "x" if entry and entry["compensation"] == "Freizeit" else "",
            fmt_hours(day["ist"]) if (not entry or entry == day["entries"][-1]) else "",
            "0,00" if first_row else "",
        ]
        for idx, val in enumerate(vals):
            c.rect(x, y, col_widths[idx] * mm, detail_row_h)
            draw_text(c, x + col_widths[idx] * mm / 2, y + 1.1 * mm, val, 5.5, False, "center")
            x += col_widths[idx] * mm
        y -= detail_row_h

    draw_text(c, left, 38 * mm, "Datum", 7)
    draw_text(c, left + 34 * mm, 38 * mm, "Mitarbeiter", 7)
    draw_text(c, left + 76 * mm, 38 * mm, "verantwortlicher Leiter", 7)
    draw_text(c, left + 142 * mm, 38 * mm, "Betriebsrat", 7)
    c.setStrokeColor(colors.grey)
    c.line(left, 42 * mm, width - 12 * mm, 42 * mm)
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.red)
    draw_text(c, left, 30 * mm, "Bitte bis zum 4.Tag des Folgemonats abgeben!", 7, True)
    c.setFillColor(colors.black)
    draw_text(c, left + 18 * mm, 22 * mm, "LA : 3121", 7)
    draw_text(c, left + 50 * mm, 22 * mm, "Mo  -  Fr", 7)
    draw_text(c, width - 76 * mm, 22 * mm, fmt_hours(data["sum_weekday"]), 7)
    draw_text(c, left + 18 * mm, 17 * mm, "LA : 3122", 7)
    draw_text(c, left + 50 * mm, 17 * mm, "Sa - So (Feiertag)", 7)
    draw_text(c, width - 76 * mm, 17 * mm, fmt_hours(data["sum_weekend"]), 7)
    draw_text(c, left + 50 * mm, 12 * mm, "Mehrarbeit", 7)
    draw_text(c, width - 76 * mm, 12 * mm, fmt_hours(data["sum_work"]), 7)
    draw_text(c, left + 18 * mm, 7 * mm, "LA : 3221", 7)
    draw_text(c, left + 50 * mm, 7 * mm, "Erschwernisse", 7)
    draw_text(c, width - 76 * mm, 7 * mm, "0,00", 7)
    c.showPage()
    c.save()
