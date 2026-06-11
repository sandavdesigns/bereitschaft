import calendar
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, time
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
        return render_template("index.html", user=user, year=year, month=month, months=MONTHS, data=data)

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
        execute(
            """
            INSERT INTO readiness (user_id, start_date, end_date, kind, start_time, end_time, hours_per_day)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                request.form["start_date"],
                request.form["end_date"],
                request.form.get("kind", "Bereitschaft"),
                request.form["start_time"],
                request.form["end_time"],
                decimal_hours(request.form["start_time"], request.form["end_time"]),
            ),
        )
        flash("Bereitschaft gespeichert.", "success")
        return redirect(month_redirect_from_form())

    @app.post("/readiness/<int:item_id>/delete")
    @login_required
    def delete_readiness(item_id):
        execute("DELETE FROM readiness WHERE id = ? AND user_id = ?", (item_id, current_user()["id"]))
        return redirect(request.referrer or url_for("index"))

    @app.route("/work", methods=["POST"])
    @login_required
    def add_work():
        user = current_user()
        execute(
            """
            INSERT INTO work_entries (user_id, work_date, start_time, end_time, note, compensation)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                request.form["work_date"],
                request.form["start_time"],
                request.form["end_time"],
                request.form.get("note", "").strip(),
                request.form.get("compensation", "Freizeit"),
            ),
        )
        flash("Einsatz gespeichert.", "success")
        return redirect(month_redirect_from_form("work_date"))

    @app.post("/work/<int:item_id>/delete")
    @login_required
    def delete_work(item_id):
        execute("DELETE FROM work_entries WHERE id = ? AND user_id = ?", (item_id, current_user()["id"]))
        return redirect(request.referrer or url_for("index"))

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
                """
            )
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


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def execute(sql, params=()):
    db = get_db()
    db.execute(sql, params)
    db.commit()


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
    start = datetime.strptime(start_value, "%H:%M").time()
    end = datetime.strptime(end_value, "%H:%M").time()
    return round(((end.hour * 60 + end.minute) - (start.hour * 60 + start.minute)) / 60, 2)


def month_redirect_from_form(date_field="start_date"):
    d = parse_date(request.form[date_field])
    return redirect(url_for("index", year=d.year, month=d.month))


def month_data(user_id, year, month):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    readiness = query_all(
        """
        SELECT * FROM readiness
        WHERE user_id = ? AND start_date <= ? AND end_date >= ?
        ORDER BY start_date, start_time
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

    days = []
    for day in range(1, last.day + 1):
        current = date(year, month, day)
        day_readiness = [
            r
            for r in readiness
            if parse_date(r["start_date"]) <= current <= parse_date(r["end_date"])
        ]
        entries = [w for w in work_entries if w["work_date"] == current.isoformat()]
        soll = sum(float(r["hours_per_day"]) for r in day_readiness)
        more = sum(decimal_hours(w["start_time"], w["end_time"]) for w in entries)
        days.append(
            {
                "date": current,
                "weekday": WEEKDAYS[current.weekday()],
                "readiness": day_readiness,
                "entries": entries,
                "soll": round(soll, 2),
                "mehrarbeit": round(more, 2),
                "ist": round(soll - more, 2),
            }
        )

    return {
        "readiness": readiness,
        "work_entries": work_entries,
        "days": days,
        "sum_soll": round(sum(d["soll"] for d in days), 2),
        "sum_work": round(sum(d["mehrarbeit"] for d in days), 2),
        "sum_weekday": round(sum(d["ist"] for d in days if d["date"].weekday() < 5), 2),
        "sum_weekend": round(sum(d["ist"] for d in days if d["date"].weekday() >= 5), 2),
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
    left = 18 * mm
    top = height - 24 * mm
    row_h = 6.0 * mm

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

    table_x = width - 112 * mm
    table_y = top - 12 * mm
    cols = [34, 23, 20, 19, 19]
    headers = ["", "Datum Beginn", "Datum Ende", "Uhrzeit von", "Uhrzeit bis"]
    for i, header in enumerate(headers):
        x = table_x + sum(cols[:i]) * mm
        c.rect(x, table_y - row_h, cols[i] * mm, row_h)
        draw_text(c, x + cols[i] * mm / 2, table_y - 4.2 * mm, header, 6.8, True, "center")
    for row_idx in range(7):
        y = table_y - (row_idx + 2) * row_h
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
            c.rect(x, y, cols[i] * mm, row_h)
            draw_text(c, x + 1 * mm, y + 1.8 * mm, val, 6.6)

    grid_x = left
    grid_y = top - 72 * mm
    col_widths = [10, 13, 13, 12, 12, 14, 34, 22, 18, 19, 17]
    headers = ["Tag", "", "Soll-Ruf-\nbereit-\nschaft", "von", "bis", "Std.", "Bemerkung", "Bezahlen\nx", "Freizeit\nx", "Ist-Rufbereit-\nschaft", "Erschwernis-\nzuschlag\nStd."]
    x = grid_x
    header_h = 17 * mm
    for idx, header in enumerate(headers):
        c.rect(x, grid_y, col_widths[idx] * mm, header_h)
        for line_no, line in enumerate(header.split("\n")):
            draw_text(c, x + col_widths[idx] * mm / 2, grid_y + header_h - (line_no + 1) * 4.2 * mm, line, 6.4, True, "center")
        x += col_widths[idx] * mm

    y = grid_y - row_h
    detail_rows = []
    for day in data["days"]:
        entries = list(day["entries"])
        detail_rows.append((day, entries[0] if entries else None, True, len(entries)))
        for extra in entries[1:]:
            detail_rows.append((day, extra, False, len(entries)))
    detail_rows = detail_rows[:38]
    red = colors.Color(0.82, 0.42, 0.42, alpha=0.65)
    for day, entry, first_row, entry_count in detail_rows:
        is_weekend = day["date"].weekday() >= 5
        if is_weekend:
            c.setFillColor(red)
            c.rect(grid_x, y, sum(col_widths) * mm, row_h, stroke=0, fill=1)
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
            c.rect(x, y, col_widths[idx] * mm, row_h)
            draw_text(c, x + col_widths[idx] * mm / 2, y + 1.8 * mm, val, 6.5, False, "center")
            x += col_widths[idx] * mm
        y -= row_h

    draw_text(c, left, 47 * mm, "Datum", 8)
    draw_text(c, left + 34 * mm, 47 * mm, "Mitarbeiter", 8)
    draw_text(c, left + 76 * mm, 47 * mm, "verantwortlicher\nLeiter", 8)
    draw_text(c, left + 142 * mm, 47 * mm, "Betriebsrat", 8)
    c.setStrokeColor(colors.grey)
    c.line(left, 51 * mm, width - 20 * mm, 51 * mm)
    c.setStrokeColor(colors.black)
    c.setFillColor(colors.red)
    draw_text(c, left, 35 * mm, "Bitte bis zum 4.Tag des Folgemonats abgeben!", 8, True)
    c.setFillColor(colors.black)
    draw_text(c, left + 18 * mm, 25 * mm, "LA : 3121", 8)
    draw_text(c, left + 50 * mm, 25 * mm, "Mo  -  Fr", 8)
    draw_text(c, width - 76 * mm, 25 * mm, fmt_hours(data["sum_weekday"]), 8)
    draw_text(c, left + 18 * mm, 19 * mm, "LA : 3122", 8)
    draw_text(c, left + 50 * mm, 19 * mm, "Sa - So (Feiertag)", 8)
    draw_text(c, width - 76 * mm, 19 * mm, fmt_hours(data["sum_weekend"]), 8)
    draw_text(c, left + 50 * mm, 13 * mm, "Mehrarbeit", 8)
    draw_text(c, width - 76 * mm, 13 * mm, fmt_hours(data["sum_work"]), 8)
    draw_text(c, left + 18 * mm, 7 * mm, "LA : 3221", 8)
    draw_text(c, left + 50 * mm, 7 * mm, "Erschwernisse", 8)
    draw_text(c, width - 76 * mm, 7 * mm, "0,00", 8)
    c.showPage()
    c.save()
