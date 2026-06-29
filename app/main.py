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
from reportlab.pdfbase import pdfmetrics
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
        selected_type_id = selected_readiness_type_id(types)
        return render_template(
            "index.html",
            user=user,
            year=year,
            month=month,
            months=MONTHS,
            data=data,
            types=types,
            selected_type_id=selected_type_id,
        )

    @app.get("/help")
    @login_required
    def help_page():
        return render_template("help.html", user=current_user())

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = query_one("SELECT * FROM users WHERE username = ?", (username,))
            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                if user["must_change_password"]:
                    return redirect(url_for("force_password_change"))
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

    @app.post("/profile/password")
    @login_required
    def change_password():
        user = current_user()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not check_password_hash(user["password_hash"], current_password):
            flash("Aktuelles Passwort ist falsch.", "error")
        elif len(new_password) < 8:
            flash("Das neue Passwort muss mindestens 8 Zeichen lang sein.", "error")
        elif new_password != confirm_password:
            flash("Die neuen Passwörter stimmen nicht überein.", "error")
        else:
            execute(
                "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                (generate_password_hash(new_password), user["id"]),
            )
            flash("Passwort geändert.", "success")
        return redirect(url_for("profile"))

    @app.route("/password/change-required", methods=["GET", "POST"])
    @login_required
    def force_password_change():
        user = current_user()
        if not user["must_change_password"]:
            return redirect(url_for("index"))
        if request.method == "POST":
            new_password = request.form.get("new_password", "")
            confirm_password = request.form.get("confirm_password", "")
            if len(new_password) < 8:
                flash("Das neue Passwort muss mindestens 8 Zeichen lang sein.", "error")
            elif new_password != confirm_password:
                flash("Die neuen Passwörter stimmen nicht überein.", "error")
            else:
                execute(
                    "UPDATE users SET password_hash = ?, must_change_password = 0 WHERE id = ?",
                    (generate_password_hash(new_password), user["id"]),
                )
                flash("Passwort geändert.", "success")
                return redirect(url_for("index"))
        return render_template("force_password_change.html", user=user)

    @app.route("/readiness", methods=["POST"])
    @login_required
    def add_readiness():
        user = current_user()
        readiness_type_id = int(request.form["readiness_type_id"])
        session["last_readiness_type_id"] = readiness_type_id
        friday_holiday_segment = request.form.get("friday_holiday_segment", "first")
        if friday_holiday_segment not in ("first", "second"):
            flash("Bitte Vormittag oder Nachmittag auswählen.", "error")
            return month_redirect()
        start_date = date_from_month_form("start_day")
        end_date = date_from_month_form("end_day")
        if end_date < start_date:
            flash("Ende darf nicht vor Beginn liegen.", "error")
            return month_redirect()
        execute(
            """
            INSERT INTO readiness (user_id, readiness_type_id, start_date, end_date, kind, start_time, end_time, hours_per_day, friday_holiday_segment)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                readiness_type_id,
                start_date.isoformat(),
                end_date.isoformat(),
                readiness_type_name(readiness_type_id),
                "00:00",
                "00:00",
                0,
                friday_holiday_segment,
            ),
        )
        flash("Bereitschaft gespeichert.", "success")
        return month_redirect(start_date.year, start_date.month)

    @app.post("/readiness/<int:item_id>/segment")
    @login_required
    def update_readiness_segment(item_id):
        segment = request.form.get("friday_holiday_segment", "first")
        if segment not in ("first", "second"):
            flash("Bitte Vormittag oder Nachmittag auswählen.", "error")
            return month_redirect()
        execute(
            "UPDATE readiness SET friday_holiday_segment = ? WHERE id = ? AND user_id = ?",
            (segment, item_id, current_user()["id"]),
        )
        flash("Freitag-Feiertag gespeichert.", "success")
        return month_redirect()

    @app.post("/readiness/<int:item_id>/delete")
    @login_required
    def delete_readiness(item_id):
        execute("DELETE FROM readiness WHERE id = ? AND user_id = ?", (item_id, current_user()["id"]))
        return month_redirect()

    @app.route("/work", methods=["POST"])
    @login_required
    def add_work():
        user = current_user()
        readiness_type_id = int(request.form["readiness_type_id"])
        session["last_readiness_type_id"] = readiness_type_id
        work_date = date_from_month_form("work_day")
        start_time = normalize_time_input(request.form["start_time"])
        end_time = normalize_time_input(request.form["end_time"])
        if not valid_time_value(start_time) or not valid_time_value(end_time):
            flash("Bitte Zeiten im Format HH:MM eingeben.", "error")
            return month_redirect(work_date.year, work_date.month)
        if not user_has_readiness_on_day(user["id"], work_date):
            flash("Einsatz kann nur an Tagen mit Bereitschaft eingetragen werden.", "error")
            return month_redirect(work_date.year, work_date.month)
        if not work_fits_readiness(user["id"], work_date, start_time, end_time):
            flash("Einsatzzeiten müssen innerhalb der Bereitschaftszeit liegen.", "error")
            return month_redirect(work_date.year, work_date.month)
        compensation = request.form.get("compensation", "Freizeit")
        if is_force_pay_holiday(work_date):
            compensation = "Bezahlen"
        execute(
            """
            INSERT INTO work_entries (user_id, readiness_type_id, work_date, start_time, end_time, note, compensation)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                readiness_type_id,
                work_date.isoformat(),
                start_time,
                end_time,
                request.form.get("note", "").strip(),
                compensation,
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
        users = query_all("SELECT id, username, role, personnel_no, first_name, last_name, must_change_password FROM users ORDER BY username")
        return render_template("admin_users.html", user=current_user(), users=users)

    @app.post("/admin/users/<int:user_id>/reset-password")
    @admin_required
    def reset_user_password(user_id):
        password = request.form.get("password", "")
        if len(password) < 8:
            flash("Das temporäre Passwort muss mindestens 8 Zeichen lang sein.", "error")
        else:
            execute(
                "UPDATE users SET password_hash = ?, must_change_password = 1 WHERE id = ?",
                (generate_password_hash(password), user_id),
            )
            flash("Passwort zurückgesetzt. Der Benutzer muss es beim nächsten Login ändern.", "success")
        return redirect(url_for("admin_users"))

    @app.route("/admin/types", methods=["GET", "POST"])
    @admin_required
    def admin_types():
        if request.method == "POST":
            type_id = request.form.get("type_id")
            values = (
                request.form.get("name", "").strip(),
                request.form.get("display_name", "").strip(),
                normalize_time_input(request.form.get("weekday_start", "")),
                normalize_time_input(request.form.get("weekday_end", "")),
                normalize_time_input(request.form.get("friday_start", "")),
                normalize_time_input(request.form.get("friday_end", "")),
                normalize_time_input(request.form.get("weekend_start", "")),
                normalize_time_input(request.form.get("weekend_end", "")),
                normalize_time_input(request.form.get("holiday_start", "")),
                normalize_time_input(request.form.get("holiday_end", "")),
            )
            if not values[0]:
                flash("Name ist Pflicht.", "error")
            elif not values[1]:
                flash("Anzeigename ist Pflicht.", "error")
            elif not all(valid_time_value(value, allow_empty=True) for value in values[2:]):
                flash("Bitte Zeiten im Format HH:MM eingeben.", "error")
            else:
                try:
                    if type_id:
                        execute(
                            """
                            UPDATE readiness_types
                            SET name = ?, display_name = ?, weekday_start = ?, weekday_end = ?, friday_start = ?, friday_end = ?,
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
                            (name, display_name, weekday_start, weekday_end, friday_start, friday_end, weekend_start, weekend_end, holiday_start, holiday_end)
                            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                            """,
                            values,
                        )
                        flash("Bereitschaftsart angelegt.", "success")
                except sqlite3.IntegrityError:
                    get_db().rollback()
                    flash("Interner Name existiert bereits.", "error")
        types = query_all(
            """
            SELECT t.*,
                   (SELECT COUNT(*) FROM readiness r WHERE r.readiness_type_id = t.id) +
                   (SELECT COUNT(*) FROM work_entries w WHERE w.readiness_type_id = t.id) AS usage_count
            FROM readiness_types t
            ORDER BY t.name
            """
        )
        return render_template("admin_types.html", user=current_user(), types=types)

    @app.post("/admin/types/<int:type_id>/toggle")
    @admin_required
    def toggle_type(type_id):
        execute("UPDATE readiness_types SET active = CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id = ?", (type_id,))
        return redirect(url_for("admin_types"))

    @app.post("/admin/types/<int:type_id>/delete")
    @admin_required
    def delete_type(type_id):
        usage = query_one(
            """
            SELECT
                (SELECT COUNT(*) FROM readiness WHERE readiness_type_id = ?) +
                (SELECT COUNT(*) FROM work_entries WHERE readiness_type_id = ?) AS count
            """,
            (type_id, type_id),
        )
        if usage and usage["count"]:
            flash("Bereitschaftsart wird bereits verwendet und kann nicht gelöscht werden.", "error")
        else:
            execute("DELETE FROM readiness_types WHERE id = ?", (type_id,))
            flash("Bereitschaftsart gelöscht.", "success")
        return redirect(url_for("admin_types"))

    @app.route("/admin/holidays", methods=["GET", "POST"])
    @admin_required
    def admin_holidays():
        year = int(request.args.get("year", datetime.now().year))
        if request.method == "POST":
            action = request.form.get("action", "save")
            if action == "seed":
                seed_thuringia_holidays(get_db(), int(request.form["year"]), replace=True)
                get_db().commit()
                flash("Thüringen-Feiertage wurden neu berechnet.", "success")
                return redirect(url_for("admin_holidays", year=request.form["year"]))
            holiday_id = request.form.get("holiday_id")
            holiday_date = request.form.get("holiday_date")
            name = request.form.get("name", "").strip()
            force_pay = 1 if request.form.get("force_pay") == "1" else 0
            if not holiday_date or not name:
                flash("Datum und Name sind Pflicht.", "error")
            elif holiday_id:
                execute(
                    "UPDATE holidays SET holiday_date = ?, name = ?, force_pay = ? WHERE id = ?",
                    (holiday_date, name, force_pay, int(holiday_id)),
                )
                flash("Feiertag gespeichert.", "success")
                year = parse_date(holiday_date).year
            else:
                try:
                    execute(
                        "INSERT INTO holidays (holiday_date, name, force_pay) VALUES (?, ?, ?)",
                        (holiday_date, name, force_pay),
                    )
                    flash("Feiertag angelegt.", "success")
                    year = parse_date(holiday_date).year
                except sqlite3.IntegrityError:
                    flash("Für dieses Datum existiert bereits ein Feiertag.", "error")
        ensure_thuringia_holidays_for_year(year)
        holidays = query_all(
            "SELECT * FROM holidays WHERE holiday_date BETWEEN ? AND ? ORDER BY holiday_date",
            (date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()),
        )
        return render_template("admin_holidays.html", user=current_user(), holidays=holidays, year=year)

    @app.post("/admin/holidays/<int:holiday_id>/delete")
    @admin_required
    def delete_holiday(holiday_id):
        row = query_one("SELECT holiday_date FROM holidays WHERE id = ?", (holiday_id,))
        year = parse_date(row["holiday_date"]).year if row else datetime.now().year
        execute("DELETE FROM holidays WHERE id = ?", (holiday_id,))
        return redirect(url_for("admin_holidays", year=year))

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
                    last_name TEXT DEFAULT '',
                    must_change_password INTEGER NOT NULL DEFAULT 0
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
                    hours_per_day REAL NOT NULL,
                    friday_holiday_segment TEXT NOT NULL DEFAULT 'first'
                );

                CREATE TABLE IF NOT EXISTS work_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    work_date TEXT NOT NULL,
                    readiness_type_id INTEGER REFERENCES readiness_types(id),
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    note TEXT NOT NULL DEFAULT '',
                    compensation TEXT NOT NULL DEFAULT 'Freizeit'
                );

                CREATE TABLE IF NOT EXISTS readiness_types (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL UNIQUE,
                    display_name TEXT NOT NULL DEFAULT '',
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

                CREATE TABLE IF NOT EXISTS holidays (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    holiday_date TEXT NOT NULL UNIQUE,
                    name TEXT NOT NULL,
                    force_pay INTEGER NOT NULL DEFAULT 0
                );
                """
            )
            ensure_column(db, "readiness", "readiness_type_id", "INTEGER REFERENCES readiness_types(id)")
            ensure_column(db, "readiness", "friday_holiday_segment", "TEXT NOT NULL DEFAULT 'first'")
            ensure_column(db, "work_entries", "readiness_type_id", "INTEGER REFERENCES readiness_types(id)")
            ensure_column(db, "users", "must_change_password", "INTEGER NOT NULL DEFAULT 0")
            ensure_column(db, "readiness_types", "display_name", "TEXT NOT NULL DEFAULT ''")
            added_force_pay = ensure_column(db, "holidays", "force_pay", "INTEGER NOT NULL DEFAULT 0")
            if added_force_pay:
                for holiday_name in FORCE_PAY_HOLIDAY_NAMES:
                    db.execute("UPDATE holidays SET force_pay = 1 WHERE name = ?", (holiday_name,))
            db.execute("UPDATE readiness_types SET display_name = name WHERE display_name = ''")
            if "friday_holiday_segment" in table_columns(db, "readiness_types"):
                db.execute(
                    """
                    UPDATE readiness
                    SET friday_holiday_segment = (
                        SELECT readiness_types.friday_holiday_segment
                        FROM readiness_types
                        WHERE readiness_types.id = readiness.readiness_type_id
                    )
                    WHERE friday_holiday_segment = 'first'
                      AND readiness_type_id IN (
                        SELECT id FROM readiness_types WHERE friday_holiday_segment = 'second'
                    )
                    """
                )
            seed_default_type(db)
            seed_thuringia_holiday_range(db, datetime.now().year - 1, datetime.now().year + 5)
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


def table_columns(db, table):
    return [row[1] for row in db.execute(f"PRAGMA table_info({table})").fetchall()]


def ensure_column(db, table, column, definition):
    if column not in table_columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        return True
    return False


def seed_default_type(db):
    existing = db.execute("SELECT id FROM readiness_types LIMIT 1").fetchone()
    if existing is None:
        db.execute(
            """
            INSERT INTO readiness_types
            (name, display_name, weekday_start, weekday_end, friday_start, friday_end, weekend_start, weekend_end, holiday_start, holiday_end)
            VALUES ('Bereitschaft', 'Bereitschaft', '12:15', '18:00', '12:15', '18:00', '06:00', '18:00', '06:00', '18:00')
            """
        )
    default_type = db.execute("SELECT id FROM readiness_types ORDER BY id LIMIT 1").fetchone()
    if default_type is not None:
        db.execute("UPDATE readiness SET readiness_type_id = ? WHERE readiness_type_id IS NULL", (default_type[0],))


def thuringia_holidays(year):
    easter = easter_sunday(year)
    return [
        (date(year, 1, 1), "Neujahr"),
        (easter - timedelta(days=2), "Karfreitag"),
        (easter + timedelta(days=1), "Ostermontag"),
        (date(year, 5, 1), "Tag der Arbeit"),
        (easter + timedelta(days=39), "Christi Himmelfahrt"),
        (easter + timedelta(days=50), "Pfingstmontag"),
        (date(year, 9, 20), "Weltkindertag"),
        (date(year, 10, 3), "Tag der Deutschen Einheit"),
        (date(year, 10, 31), "Reformationstag"),
        (date(year, 12, 25), "1. Weihnachtstag"),
        (date(year, 12, 26), "2. Weihnachtstag"),
    ]


FORCE_PAY_HOLIDAY_NAMES = {
    "Neujahr",
    "Karfreitag",
    "Ostermontag",
    "Tag der Arbeit",
    "Christi Himmelfahrt",
    "Pfingstmontag",
    "Weltkindertag",
    "Tag der Deutschen Einheit",
    "Reformationstag",
    "1. Weihnachtsfeiertag",
    "2. Weihnachtsfeiertag",
    "1. Weihnachtstag",
    "2. Weihnachtstag",
}


def seed_thuringia_holiday_range(db, start_year, end_year, replace=False):
    for year in range(start_year, end_year + 1):
        seed_thuringia_holidays(db, year, replace=replace)


def seed_thuringia_holidays(db, year, replace=False):
    if replace:
        db.execute(
            "DELETE FROM holidays WHERE holiday_date BETWEEN ? AND ?",
            (date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()),
        )
    for holiday_date, name in thuringia_holidays(year):
        db.execute(
            "INSERT OR IGNORE INTO holidays (holiday_date, name, force_pay) VALUES (?, ?, ?)",
            (holiday_date.isoformat(), name, 1 if name in FORCE_PAY_HOLIDAY_NAMES else 0),
        )


def ensure_thuringia_holidays_for_year(year):
    db = get_db()
    seed_thuringia_holidays(db, year, replace=False)
    db.commit()


def query_one(sql, params=()):
    return get_db().execute(sql, params).fetchone()


def query_all(sql, params=()):
    return get_db().execute(sql, params).fetchall()


def execute(sql, params=()):
    db = get_db()
    db.execute(sql, params)
    db.commit()


def readiness_type_name(type_id):
    row = query_one("SELECT display_name, name FROM readiness_types WHERE id = ?", (type_id,))
    if not row:
        return "Bereitschaft"
    return row["display_name"] or row["name"]


def selected_readiness_type_id(types):
    type_ids = [int(item["id"]) for item in types]
    selected = session.get("last_readiness_type_id")
    if selected in type_ids:
        return selected
    return type_ids[0] if type_ids else None


def normalize_time_input(value):
    value = (value or "").strip()
    if not value:
        return ""
    if value.isdigit():
        hour = int(value)
        if 0 <= hour <= 23:
            return f"{hour:02d}:00"
    if ":" in value:
        parts = value.split(":", 1)
        if parts[0].isdigit() and (parts[1] == "" or parts[1].isdigit()):
            hour = int(parts[0])
            minute = int(parts[1] or "0")
            if 0 <= hour <= 23 and 0 <= minute <= 59:
                return f"{hour:02d}:{minute:02d}"
    return value


def valid_time_value(value, allow_empty=False):
    value = (value or "").strip()
    if not value:
        return allow_empty
    if len(value) != 5 or value[2] != ":":
        return False
    hour, minute = value.split(":", 1)
    if not hour.isdigit() or not minute.isdigit():
        return False
    return 0 <= int(hour) <= 23 and 0 <= int(minute) <= 59


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if user is None:
            return redirect(url_for("login"))
        if user["must_change_password"] and request.endpoint not in ("force_password_change", "logout", "static"):
            return redirect(url_for("force_password_change"))
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


def holiday_dates_for_year(year):
    ensure_thuringia_holidays_for_year(year)
    rows = query_all(
        "SELECT holiday_date FROM holidays WHERE holiday_date BETWEEN ? AND ?",
        (date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()),
    )
    return {parse_date(row["holiday_date"]) for row in rows}


def force_pay_holiday_dates_for_year(year):
    ensure_thuringia_holidays_for_year(year)
    rows = query_all(
        "SELECT holiday_date FROM holidays WHERE holiday_date BETWEEN ? AND ? AND force_pay = 1",
        (date(year, 1, 1).isoformat(), date(year, 12, 31).isoformat()),
    )
    return {parse_date(row["holiday_date"]) for row in rows}


def is_holiday(day, holiday_dates=None):
    if holiday_dates is None:
        holiday_dates = holiday_dates_for_year(day.year)
    return day in holiday_dates


def is_force_pay_holiday(day, force_pay_holiday_dates=None):
    if force_pay_holiday_dates is None:
        force_pay_holiday_dates = force_pay_holiday_dates_for_year(day.year)
    return day in force_pay_holiday_dates


def rule_for_day(readiness_type, day, holiday_dates=None):
    if is_holiday(day, holiday_dates):
        start, end = readiness_type["holiday_start"], readiness_type["holiday_end"]
        if start and end and day.weekday() == 4:
            start, end, hours = split_friday_holiday_interval(start, end, readiness_type["friday_holiday_segment"])
        else:
            hours = None
    elif day.weekday() == 4:
        start, end = readiness_type["friday_start"], readiness_type["friday_end"]
        hours = None
    elif day.weekday() >= 5:
        start, end = readiness_type["weekend_start"], readiness_type["weekend_end"]
        hours = None
    else:
        start, end = readiness_type["weekday_start"], readiness_type["weekday_end"]
        hours = None
    if not start or not end:
        return None
    return {"start_time": start, "end_time": end, "hours": hours if hours is not None else interval_hours(start, end)}


def work_remark(day_readiness, note):
    kinds = []
    for item in day_readiness:
        if item["kind"] not in kinds:
            kinds.append(item["kind"])
    prefix = "/".join(kinds)
    note = (note or "").strip()
    if prefix and note:
        return f"{prefix} - {note}"
    return prefix or note


def readiness_kind(item):
    return item["type_display_name"] or item["type_name"] or item["kind"]


def friday_holiday_segment_label(segment):
    return "Nachmittag" if segment == "second" else "Vormittag"


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


def user_has_readiness_on_day(user_id, day):
    return len(readiness_rules_for_day(user_id, day)) > 0


def readiness_rules_for_day(user_id, day):
    holiday_dates = holiday_dates_for_year(day.year)
    rows = query_all(
        """
        SELECT r.*, t.name AS type_name, t.display_name AS type_display_name,
               t.weekday_start, t.weekday_end, t.friday_start, t.friday_end,
               t.weekend_start, t.weekend_end, t.holiday_start, t.holiday_end
        FROM readiness r
        LEFT JOIN readiness_types t ON t.id = r.readiness_type_id
        WHERE r.user_id = ? AND r.start_date <= ? AND r.end_date >= ?
        ORDER BY r.start_date, r.id
        """,
        (user_id, day.isoformat(), day.isoformat()),
    )
    rules = []
    for row in rows:
        rule = rule_for_day(row, day, holiday_dates)
        if rule:
            rules.append(rule)
    return rules


def minutes_from_time(value):
    parsed = datetime.strptime(value, "%H:%M").time()
    return parsed.hour * 60 + parsed.minute


def normalized_interval(start_value, end_value):
    start = minutes_from_time(start_value)
    end = minutes_from_time(end_value)
    if end <= start:
        end += 24 * 60
    return start, end


def minutes_to_time(value):
    value = value % (24 * 60)
    return f"{value // 60:02d}:{value % 60:02d}"


def interval_hours(start_value, end_value):
    start, end = normalized_interval(start_value, end_value)
    return round((end - start) / 60, 2)


def split_friday_holiday_interval(start_value, end_value, segment):
    start, end = normalized_interval(start_value, end_value)
    middle = start + int((end - start) / 2)
    if segment == "second":
        return minutes_to_time(middle), end_value, round((end - middle) / 60, 2)
    if segment == "full":
        return start_value, end_value, round((end - start) / 60, 2)
    return start_value, minutes_to_time(middle), round((middle - start) / 60, 2)


def work_fits_readiness(user_id, day, start_time, end_time):
    work_start, work_end = normalized_interval(start_time, end_time)
    for rule in readiness_rules_for_day(user_id, day):
        ready_start, ready_end = normalized_interval(rule["start_time"], rule["end_time"])
        current_work_start = work_start
        current_work_end = work_end
        if ready_end > 24 * 60 and current_work_start < ready_start:
            current_work_start += 24 * 60
            current_work_end += 24 * 60
        if current_work_start >= ready_start and current_work_end <= ready_end:
            return True
    return False


def month_data(user_id, year, month):
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    holiday_dates = holiday_dates_for_year(year)
    force_pay_holiday_dates = force_pay_holiday_dates_for_year(year)
    readiness = query_all(
        """
        SELECT r.*, t.name AS type_name, t.display_name AS type_display_name,
               t.weekday_start, t.weekday_end, t.friday_start, t.friday_end,
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
        SELECT w.*, t.name AS type_name, t.display_name AS type_display_name
        FROM work_entries w
        LEFT JOIN readiness_types t ON t.id = w.readiness_type_id
        WHERE w.user_id = ? AND w.work_date BETWEEN ? AND ?
        ORDER BY w.work_date, w.start_time
        """,
        (user_id, first.isoformat(), last.isoformat()),
    )

    readiness_display = []
    for item in readiness:
        item_start = max(parse_date(item["start_date"]), first)
        item_end = min(parse_date(item["end_date"]), last)
        for current in daterange(item_start, item_end):
            rule = rule_for_day(item, current, holiday_dates)
            if rule:
                readiness_display.append(
                    {
                        "id": item["id"],
                        "kind": item["type_display_name"] or item["type_name"] or item["kind"],
                        "start_date": current.isoformat(),
                        "end_date": current.isoformat(),
                        "start_time": rule["start_time"],
                        "end_time": rule["end_time"],
                        "friday_holiday_segment": item["friday_holiday_segment"],
                        "friday_holiday_segment_label": friday_holiday_segment_label(item["friday_holiday_segment"]),
                    }
                )

    days = []
    month_work_entries = []
    for day in range(1, last.day + 1):
        current = date(year, month, day)
        day_readiness = []
        remark_readiness = []
        for r in readiness:
            if parse_date(r["start_date"]) <= current <= parse_date(r["end_date"]):
                remark_readiness.append({"kind": readiness_kind(r)})
                rule = rule_for_day(r, current, holiday_dates)
                if rule:
                    day_readiness.append(
                        {
                            "id": r["id"],
                            "kind": readiness_kind(r),
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
                        "remark": work_remark([{"kind": w["type_display_name"] or w["type_name"]}] if (w["type_display_name"] or w["type_name"]) else remark_readiness, w["note"]),
                        "compensation": w["compensation"],
                        "hours": decimal_hours(w["start_time"], w["end_time"]),
                    }
                )
                month_work_entries.append(entries[-1])
        soll = sum(float(r["hours_per_day"]) for r in day_readiness)
        more = sum(w["hours"] for w in entries)
        days.append(
            {
                "date": current,
                "weekday": WEEKDAYS[current.weekday()],
                "holiday": is_holiday(current, holiday_dates),
                "force_pay_holiday": is_force_pay_holiday(current, force_pay_holiday_dates),
                "remark": work_remark(remark_readiness, ""),
                "readiness": day_readiness,
                "entries": entries,
                "soll": round(soll, 2),
                "mehrarbeit": round(more, 2),
                "ist": round(soll - more, 2),
            }
        )

    sum_weekday = round(sum(d["ist"] for d in days if d["date"].weekday() < 5 and not d["holiday"]), 2)
    sum_weekend = round(sum(d["ist"] for d in days if d["date"].weekday() >= 5 or d["holiday"]), 2)
    readiness_split = len(readiness_display) if len(readiness_display) <= 8 else (len(readiness_display) + 1) // 2
    return {
        "readiness": readiness_display,
        "readiness_columns": [column for column in (readiness_display[:readiness_split], readiness_display[readiness_split:]) if column],
        "has_readiness": len(readiness) > 0,
        "work_entries": month_work_entries,
        "days": days,
        "sum_soll": round(sum(d["soll"] for d in days), 2),
        "sum_readiness": round(sum_weekday + sum_weekend, 2),
        "sum_work": round(sum(d["mehrarbeit"] for d in days), 2),
        "sum_work_paid": round(sum(w["hours"] for w in month_work_entries if w["compensation"] == "Bezahlen"), 2),
        "sum_work_leisure": round(sum(w["hours"] for w in month_work_entries if w["compensation"] == "Freizeit"), 2),
        "sum_weekday": sum_weekday,
        "sum_weekend": sum_weekend,
    }


def draw_text(c, x, y, text, size=8, bold=False, align="left"):
    c.setFont("Helvetica-Bold" if bold else "Helvetica", size)
    if align == "right":
        c.drawRightString(x, y, text)
    elif align == "center":
        c.drawCentredString(x, y, text)
    else:
        c.drawString(x, y, text)


def fitted_text(c, text, max_width, size=8, bold=False):
    text = str(text or "")
    font_name = "Helvetica-Bold" if bold else "Helvetica"
    if c.stringWidth(text, font_name, size) <= max_width:
        return text
    suffix = "..."
    while text and c.stringWidth(text + suffix, font_name, size) > max_width:
        text = text[:-1]
    return text + suffix if text else ""


def draw_fitted_text(c, x, y, text, max_width, size=8, bold=False, align="left", min_size=None):
    text = str(text or "")
    draw_size = size
    if min_size is not None:
        font_name = "Helvetica-Bold" if bold else "Helvetica"
        while draw_size > min_size and c.stringWidth(text, font_name, draw_size) > max_width:
            draw_size = max(min_size, draw_size - 0.2)
    draw_text(c, x, y, fitted_text(c, text, max_width, draw_size, bold), draw_size, bold, align)


def centered_text_baseline(y, height, size, bold=False):
    font_name = "Helvetica-Bold" if bold else "Helvetica"
    ascent = pdfmetrics.getAscent(font_name, size)
    descent = pdfmetrics.getDescent(font_name, size)
    return y + (height - (ascent - descent)) / 2 - descent


def fmt_hours(value):
    if value in ("", None):
        return ""
    return f"{float(value):.2f}".replace(".", ",")


def render_month_pdf(buffer, user, data, year, month):
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    left = 12 * mm
    top = height - 22 * mm
    compact_top = len(data["readiness"]) > 8
    top_row_h = (3.7 if compact_top else 5.0) * mm

    draw_text(c, left, top, "Rufbereitschaft", 11, True)
    c.line(left, top - 1, left + 28 * mm, top - 1)
    draw_text(c, width - 62 * mm, top, "Monat:", 8, True)
    draw_text(c, width - 28 * mm, top, f"{MONTHS[month-1][:3]} {str(year)[2:]}", 8, True)

    col_widths = [9, 11, 13, 12, 12, 13, 36, 20, 18, 19, 16]
    main_table_right = left + sum(col_widths) * mm
    table_width_mm = 58 if compact_top else 125
    table_x = main_table_right - (table_width_mm * (2 if compact_top else 1) + (3 if compact_top else 0)) * mm
    table_y = top - 12 * mm
    cols = [14, 13, 13, 9, 9] if compact_top else [34, 27, 27, 18.5, 18.5]

    person_rows = [
        ("Pers.-Nr.:", user["personnel_no"] or ""),
        ("Vorname:", user["first_name"] or ""),
        ("Name:", user["last_name"] or ""),
    ]
    person_value_x = left + 22 * mm
    person_value_width = max(12 * mm, table_x - person_value_x - 3 * mm)
    for row_idx, (label, value) in enumerate(person_rows):
        y = top - (18 + row_idx * 11) * mm
        draw_text(c, left, y, label, 8, True)
        draw_fitted_text(c, person_value_x, y, value, person_value_width, 8, True)

    headers = ["", "Datum Beginn", "Datum Ende", "Uhrzeit von", "Uhrzeit bis"]
    top_rows = 8 if compact_top else 7
    split_at = len(data["readiness"]) if not compact_top else top_rows
    readiness_columns = [column for column in (data["readiness"][:split_at], data["readiness"][split_at:]) if column]
    top_rows = max(max((len(column) for column in readiness_columns), default=0), top_rows)
    table_width = table_width_mm * mm
    for col_idx, column in enumerate(readiness_columns):
        current_x = table_x + col_idx * (table_width + 3 * mm)
        for i, header in enumerate(headers):
            x = current_x + sum(cols[:i]) * mm
            c.rect(x, table_y - top_row_h, cols[i] * mm, top_row_h)
            draw_fitted_text(c, x + cols[i] * mm / 2, table_y - (2.7 if compact_top else 3.45) * mm, header, cols[i] * mm - 1 * mm, 5.7 if compact_top else 6.6, True, "center")
        for row_idx in range(top_rows):
            y = table_y - (row_idx + 2) * top_row_h
            item = column[row_idx] if row_idx < len(column) else None
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
                x = current_x + sum(cols[:i]) * mm
                c.rect(x, y, cols[i] * mm, top_row_h)
                draw_fitted_text(c, x + 0.7 * mm, y + (1.05 if compact_top else 1.35) * mm, val, cols[i] * mm - 1.4 * mm, 5.8 if compact_top else 6.6)

    grid_x = left
    headers = ["Tag", "", "Soll-Ruf-\nbereit-\nschaft", "von", "bis", "Std.", "Bemerkung", "Bezahlen\nx", "Freizeit\nx", "Ist-Rufbereit-\nschaft", "Erschwernis-\nzuschlag\nStd."]
    x = grid_x
    header_h = 12 * mm
    grid_y = min(top - 68 * mm, table_y - (top_rows + 2) * top_row_h - header_h - 2 * mm)
    for idx, header in enumerate(headers):
        c.rect(x, grid_y, col_widths[idx] * mm, header_h)
        for line_no, line in enumerate(header.split("\n")):
            draw_fitted_text(c, x + col_widths[idx] * mm / 2, grid_y + header_h - (line_no + 1) * 3.15 * mm, line, col_widths[idx] * mm - 1 * mm, 5.8, True, "center")
        x += col_widths[idx] * mm

    detail_rows = []
    for day in data["days"]:
        entries = list(day["entries"])
        detail_rows.append((day, entries[0] if entries else None, True, len(entries)))
        for extra in entries[1:]:
            detail_rows.append((day, extra, False, len(entries)))
    detail_rows = detail_rows[:36]
    detail_row_h = min(5.2 * mm, max(3.4 * mm, (grid_y - 58 * mm) / max(len(detail_rows), 1)))
    detail_font_size = 7.8 if detail_row_h >= 4.4 * mm else 7.0
    y = grid_y - detail_row_h
    red = colors.Color(0.82, 0.42, 0.42, alpha=0.65)
    for day, entry, first_row, entry_count in detail_rows:
        is_weekend = day["date"].weekday() >= 5 or day.get("holiday")
        if is_weekend:
            c.setFillColor(red)
            c.rect(grid_x, y, sum(col_widths) * mm, detail_row_h, stroke=0, fill=1)
            c.setFillColor(colors.black)
        pay_marker = ""
        leisure_marker = ""
        if entry and entry["compensation"] == "Bezahlen":
            pay_marker = "x"
        if entry and entry["compensation"] == "Freizeit":
            leisure_marker = "x"
        x = grid_x
        vals = [
            day["weekday"] if first_row else "",
            f"{day['date'].day}." if first_row else "",
            fmt_hours(day["soll"]) if first_row and day["soll"] else "",
            entry["start_time"] if entry else "",
            entry["end_time"] if entry else "",
            fmt_hours(decimal_hours(entry["start_time"], entry["end_time"])) if entry else "0,00",
            entry["remark"] if entry else day["remark"],
            pay_marker,
            leisure_marker,
            fmt_hours(day["ist"]) if (not entry or entry == day["entries"][-1]) else "",
            "0,00" if first_row else "",
        ]
        for idx, val in enumerate(vals):
            c.rect(x, y, col_widths[idx] * mm, detail_row_h)
            draw_fitted_text(c, x + col_widths[idx] * mm / 2, centered_text_baseline(y, detail_row_h, detail_font_size), val, col_widths[idx] * mm - 1 * mm, detail_font_size, False, "center", 6.2)
            x += col_widths[idx] * mm
        y -= detail_row_h

    std_total_x = grid_x + sum(col_widths[:5]) * mm
    std_total_y = y
    std_total_w = col_widths[5] * mm
    c.rect(std_total_x, std_total_y, std_total_w, detail_row_h)
    draw_fitted_text(
        c,
        std_total_x + std_total_w / 2,
        centered_text_baseline(std_total_y, detail_row_h, detail_font_size),
        fmt_hours(data["sum_work"]),
        std_total_w - 1 * mm,
        detail_font_size,
        True,
        "center",
        6.2,
    )

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
    draw_text(c, left + 18 * mm, 24 * mm, "LA : 3121", 7)
    draw_text(c, left + 50 * mm, 24 * mm, "Mo  -  Fr", 7)
    draw_text(c, width - 76 * mm, 24 * mm, fmt_hours(data["sum_weekday"]), 7)
    draw_text(c, left + 18 * mm, 20 * mm, "LA : 3122", 7)
    draw_text(c, left + 50 * mm, 20 * mm, "Sa - So (Feiertag)", 7)
    draw_text(c, width - 76 * mm, 20 * mm, fmt_hours(data["sum_weekend"]), 7)
    draw_text(c, left + 50 * mm, 16 * mm, "Mehrarbeit bezahlt", 7)
    draw_text(c, width - 76 * mm, 16 * mm, fmt_hours(data["sum_work_paid"]), 7)
    draw_text(c, left + 50 * mm, 12 * mm, "Mehrarbeit Freizeit", 7)
    draw_text(c, width - 76 * mm, 12 * mm, fmt_hours(data["sum_work_leisure"]), 7)
    draw_text(c, left + 18 * mm, 8 * mm, "LA : 3221", 7)
    draw_text(c, left + 50 * mm, 8 * mm, "Erschwernisse", 7)
    draw_text(c, width - 76 * mm, 8 * mm, "0,00", 7)
    c.showPage()
    c.save()
