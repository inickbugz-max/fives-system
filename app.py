from flask import Flask, render_template, request, redirect, session, url_for, jsonify, make_response
import sqlite3
from datetime import datetime, timedelta
import traceback
import csv
import io

app = Flask(__name__)
app.secret_key = "your-secret-key-change-in-production"

# -----------------------------
# DATABASE INITIALISATION
# -----------------------------
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    # Bookings table
    c.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            phone TEXT,
            court TEXT,
            time TEXT,
            date TEXT,
            booking_type TEXT,
            amount INTEGER,
            paid INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Social payments table
    c.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            payer_name TEXT,
            amount INTEGER,
            method TEXT,
            date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id)
        )
    """)

    # Divisions table
    c.execute("""
        CREATE TABLE IF NOT EXISTS divisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            match_duration INTEGER DEFAULT 45,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    default_divisions = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for div in default_divisions:
        c.execute("INSERT OR IGNORE INTO divisions (name) VALUES (?)", (div,))

    # Teams table
    c.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            captain TEXT,
            total_league_fee INTEGER DEFAULT 0,
            division_id INTEGER,
            points INTEGER DEFAULT 0,
            points_adj INTEGER DEFAULT 0,
            played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            goals_for INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (division_id) REFERENCES divisions (id),
            UNIQUE(name, division_id)
        )
    """)
    try:
        c.execute("ALTER TABLE teams ADD COLUMN division_id INTEGER")
        c.execute("ALTER TABLE teams ADD COLUMN points_adj INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # League matches table
    c.execute("""
        CREATE TABLE IF NOT EXISTS league_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            division_id INTEGER,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_score INTEGER DEFAULT 0,
            away_score INTEGER DEFAULT 0,
            referee TEXT,
            status TEXT DEFAULT 'scheduled',
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id),
            FOREIGN KEY (division_id) REFERENCES divisions (id),
            FOREIGN KEY (home_team_id) REFERENCES teams (id),
            FOREIGN KEY (away_team_id) REFERENCES teams (id)
        )
    """)
    try:
        c.execute("ALTER TABLE league_matches ADD COLUMN division_id INTEGER")
        c.execute("ALTER TABLE league_matches ADD COLUMN payment_status TEXT DEFAULT 'unpaid'")
        c.execute("ALTER TABLE league_matches ADD COLUMN paid_amount INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # League payments table
    c.execute("""
        CREATE TABLE IF NOT EXISTS league_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            team_id INTEGER,
            player_name TEXT,
            amount INTEGER,
            method TEXT,
            date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id),
            FOREIGN KEY (team_id) REFERENCES teams (id)
        )
    """)
    try:
        c.execute("ALTER TABLE league_payments ADD COLUMN booking_id INTEGER")
        c.execute("ALTER TABLE league_payments ADD COLUMN player_name TEXT")
    except sqlite3.OperationalError:
        pass

    # Cash days table
    c.execute("""
        CREATE TABLE IF NOT EXISTS cash_days (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT UNIQUE,
            start_cash INTEGER DEFAULT 0,
            counted_cash INTEGER DEFAULT 0,
            counted_at TIMESTAMP
        )
    """)
    try:
        c.execute("ALTER TABLE cash_days ADD COLUMN counted_at TIMESTAMP")
    except sqlite3.OperationalError:
        pass

    # Expenses table
    c.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            supplier TEXT,
            invoice_no TEXT,
            amount INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staff table
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staff duty records
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff_duty (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT,
            staff_id INTEGER,
            shift TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (staff_id) REFERENCES staff (id)
        )
    """)

    # Staff shift records
    c.execute("""
        CREATE TABLE IF NOT EXISTS staff_shift_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            staff_id INTEGER,
            date TEXT,
            shift TEXT,
            hours_worked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (staff_id) REFERENCES staff (id),
            UNIQUE(staff_id, date, shift)
        )
    """)

    # Referee records table
    c.execute("""
        CREATE TABLE IF NOT EXISTS referee_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referee_name TEXT,
            match_id INTEGER,
            date TEXT,
            fee INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (match_id) REFERENCES league_matches (id)
        )
    """)

    conn.commit()
    conn.close()

init_db()

# -----------------------------
# LOGIN / LOGOUT
# -----------------------------
@app.route("/", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        session["user"] = request.form["username"]
        return redirect(url_for("dashboard"))
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

# -----------------------------
# DASHBOARD
# -----------------------------
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect(url_for("login"))

    date_str = request.args.get("date")
    if date_str:
        try:
            today = datetime.strptime(date_str, "%Y-%m-%d").strftime("%Y-%m-%d")
        except ValueError:
            today = datetime.now().strftime("%Y-%m-%d")
    else:
        today = datetime.now().strftime("%Y-%m-%d")

    times = [f"{h:02d}:00" for h in range(6, 24)]
    courts = ["Court 2 (5s)", "Court 3 (5s)", "Court 4 (7s)"]

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    bookings = c.execute(
        "SELECT * FROM bookings WHERE date = ? ORDER BY time, court",
        (today,)
    ).fetchall()

    schedule = {}
    for t in times:
        schedule[t] = {}
        for c_name in courts:
            schedule[t][c_name] = None
    for b in bookings:
        time_val = b[4]
        court_val = b[3]
        schedule[time_val][court_val] = b

    total_bookings_day = len(bookings)
    total_amount_day = sum(int(b[7]) for b in bookings if b[7]) if bookings else 0
    total_paid_day = sum(int(b[8]) for b in bookings if b[8]) if bookings else 0
    total_outstanding_day = total_amount_day - total_paid_day

    all_payments = c.execute("SELECT SUM(amount) FROM payments").fetchone()[0] or 0
    all_bookings = c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] or 0

    # Payment breakdown
    social_cash = c.execute("""
        SELECT SUM(p.amount) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'cash' AND b.booking_type = 'social'
    """).fetchone()[0] or 0
    social_card = c.execute("""
        SELECT SUM(p.amount) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'card' AND b.booking_type = 'social'
    """).fetchone()[0] or 0
    social_eft = c.execute("""
        SELECT SUM(p.amount) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'eft' AND b.booking_type = 'social'
    """).fetchone()[0] or 0

    league_cash = c.execute("""
        SELECT SUM(amount) FROM league_payments WHERE method = 'cash'
    """).fetchone()[0] or 0
    league_card = c.execute("""
        SELECT SUM(amount) FROM league_payments WHERE method = 'card'
    """).fetchone()[0] or 0
    league_eft = c.execute("""
        SELECT SUM(amount) FROM league_payments WHERE method = 'eft'
    """).fetchone()[0] or 0

    social_total = social_cash + social_card + social_eft
    league_total = league_cash + league_card + league_eft
    total_cash = social_cash + league_cash
    total_card = social_card + league_card
    total_eft = social_eft + league_eft
    total_all_payments = total_cash + total_card + total_eft

    today_expenses = c.execute("""
        SELECT SUM(amount) FROM expenses WHERE date = ?
    """, (today,)).fetchone()[0] or 0

    today_cash_income = c.execute("""
        SELECT SUM(amount) FROM (
            SELECT p.amount FROM payments p
            JOIN bookings b ON p.booking_id = b.id
            WHERE p.method = 'cash' AND p.date = ?
            UNION ALL
            SELECT amount FROM league_payments WHERE method = 'cash' AND date = ?
        )
    """, (today, today)).fetchone()[0] or 0

    start_cash_row = c.execute("SELECT start_cash FROM cash_days WHERE date = ?", (today,)).fetchone()
    start_cash = start_cash_row[0] if start_cash_row else 0
    final_cash = start_cash + today_cash_income - today_expenses

    staff_on_duty = c.execute("""
        SELECT s.name, sd.shift FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = ?
        ORDER BY sd.shift
    """, (today,)).fetchall()

    conn.close()

    return render_template(
        "dashboard.html",
        schedule=schedule,
        times=times,
        courts=courts,
        today=today,
        user=session.get("user"),
        error=request.args.get("error"),
        total_bookings_day=total_bookings_day,
        total_amount_day=total_amount_day,
        total_paid_day=total_paid_day,
        total_outstanding_day=total_outstanding_day,
        all_revenue=all_payments,
        all_bookings=all_bookings,
        social_cash=social_cash,
        social_card=social_card,
        social_eft=social_eft,
        social_total=social_total,
        league_cash=league_cash,
        league_card=league_card,
        league_eft=league_eft,
        league_total=league_total,
        total_cash=total_cash,
        total_card=total_card,
        total_eft=total_eft,
        total_all_payments=total_all_payments,
        today_expenses=today_expenses,
        start_cash=start_cash,
        today_cash_income=today_cash_income,
        final_cash=final_cash,
        staff_on_duty=staff_on_duty
    )

# -----------------------------
# ADD BOOKING
# -----------------------------
@app.route("/add", methods=["POST"])
def add_booking():
    if "user" not in session:
        return redirect(url_for("login"))

    name = request.form["name"]
    phone = request.form["phone"]
    court = request.form["court"]
    time = request.form["time"]
    booking_type = request.form["booking_type"]
    duration = int(request.form.get("duration", 1))
    today = datetime.now().strftime("%Y-%m-%d")
    amount = 0
    if booking_type in ['social', 'league', 'open_social']:
        amount = int(request.form.get("amount", 0))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    start_hour = int(time.split(':')[0])
    conflict = False
    for i in range(duration):
        slot_hour = start_hour + i
        if slot_hour > 23:
            conflict = True
            break
        slot_time = f"{slot_hour:02d}:00"
        existing = c.execute(
            "SELECT id FROM bookings WHERE court = ? AND time = ? AND date = ?",
            (court, slot_time, today)
        ).fetchone()
        if existing:
            conflict = True
            break

    if conflict:
        conn.close()
        return redirect(url_for("dashboard", error="Time slot(s) not available for full duration"))

    booking_ids = []
    for i in range(duration):
        slot_hour = start_hour + i
        slot_time = f"{slot_hour:02d}:00"
        c.execute("""
            INSERT INTO bookings (name, phone, court, time, date, booking_type, amount, paid, duration)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (name, phone, court, slot_time, today, booking_type, amount, duration))
        booking_id = c.lastrowid
        booking_ids.append(booking_id)

    if booking_type == "league":
        division_id = request.form.get("division_id")
        home_team_id = request.form.get("home_team_id")
        away_team_id = request.form.get("away_team_id")
        referee = request.form.get("referee", "")
        if division_id and home_team_id and away_team_id:
            c.execute("""
                INSERT INTO league_matches (booking_id, division_id, home_team_id, away_team_id, referee, status, payment_status, paid_amount)
                VALUES (?, ?, ?, ?, ?, 'scheduled', 'unpaid', 0)
            """, (booking_ids[0], division_id, home_team_id, away_team_id, referee))

    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))

# -----------------------------
# RECORD PAYMENT
# -----------------------------
@app.route("/payment/<int:booking_id>", methods=["POST"])
def record_payment(booking_id):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    booking = c.execute("SELECT booking_type FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if not booking:
        conn.close()
        return "Booking not found", 404

    booking_type = booking[0]
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        if booking_type == "social":
            payer_name = request.form["payer_name"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            c.execute("""
                INSERT INTO payments (booking_id, payer_name, amount, method, date)
                VALUES (?, ?, ?, ?, ?)
            """, (booking_id, payer_name, amount, method, today))
            c.execute("UPDATE bookings SET paid = paid + ? WHERE id = ?", (amount, booking_id))
        elif booking_type == "league":
            team_id = request.form["team_id"]
            player_name = request.form["player_name"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            notes = request.form.get("notes", "")
            c.execute("""
                INSERT INTO league_payments (booking_id, team_id, player_name, amount, method, date, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (booking_id, team_id, player_name, amount, method, today, notes))
            c.execute("""
                UPDATE league_matches
                SET paid_amount = paid_amount + ?,
                    payment_status = CASE WHEN paid_amount + ? >= (SELECT amount FROM bookings WHERE id = ?) THEN 'paid' ELSE 'partial' END
                WHERE booking_id = ?
            """, (amount, amount, booking_id, booking_id))

        conn.commit()
        conn.close()

        referer = request.headers.get("Referer")
        if referer:
            return redirect(referer)
        return redirect(url_for("dashboard"))
    except Exception as e:
        conn.close()
        print("ERROR in payment:", traceback.format_exc())
        return f"Payment failed: {str(e)}", 500

# -----------------------------
# VIEW ALL BOOKINGS
# -----------------------------
@app.route("/bookings")
def bookings_list():
    if "user" not in session:
        return redirect(url_for("login"))

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    bookings = c.execute(
        "SELECT * FROM bookings ORDER BY date DESC, time"
    ).fetchall()
    conn.close()
    return render_template("bookings.html", bookings=bookings, user=session.get("user"))

# -----------------------------
# AJAX ENDPOINTS
# -----------------------------
@app.route("/api/payments/<int:booking_id>")
def get_payments(booking_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    social_payments = c.execute("""
        SELECT payer_name, amount, method, date, 'social' as type, NULL as team_name
        FROM payments
        WHERE booking_id = ?
        ORDER BY created_at
    """, (booking_id,)).fetchall()
    league_payments = c.execute("""
        SELECT lp.player_name, lp.amount, lp.method, lp.date, 'league' as type, t.name as team_name
        FROM league_payments lp
        JOIN teams t ON lp.team_id = t.id
        WHERE lp.booking_id = ?
        ORDER BY lp.created_at
    """, (booking_id,)).fetchall()
    conn.close()

    all_payments = []
    for p in social_payments:
        all_payments.append({
            "payer": p[0], "amount": p[1], "method": p[2], "date": p[3],
            "type": p[4], "team": None
        })
    for p in league_payments:
        all_payments.append({
            "payer": p[0], "amount": p[1], "method": p[2], "date": p[3],
            "type": p[4], "team": p[5]
        })
    all_payments.sort(key=lambda x: x["date"])
    return jsonify(all_payments)

@app.route("/api/booking/<int:booking_id>")
def get_booking(booking_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    booking = c.execute(
        "SELECT id, name, amount, paid, booking_type FROM bookings WHERE id = ?",
        (booking_id,)
    ).fetchone()
    conn.close()
    if not booking:
        return jsonify({"error": "Booking not found"}), 404
    return jsonify({
        "id": booking[0],
        "name": booking[1],
        "amount": booking[2],
        "paid": booking[3],
        "booking_type": booking[4]
    })

@app.route("/api/teams")
def api_teams():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    division_id = request.args.get("division_id", type=int)
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if division_id:
        teams = c.execute("SELECT id, name FROM teams WHERE division_id = ? ORDER BY name", (division_id,)).fetchall()
    else:
        teams = c.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"id": t[0], "name": t[1]} for t in teams])

@app.route("/api/divisions")
def api_divisions():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    divisions = c.execute("SELECT id, name, match_duration FROM divisions ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"id": d[0], "name": d[1], "duration": d[2]} for d in divisions])

# -----------------------------
# LEAGUE MANAGEMENT
# -----------------------------
def update_standings(division_id=None):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    if division_id:
        c.execute("UPDATE teams SET points=0, played=0, wins=0, draws=0, losses=0, goals_for=0, goals_against=0 WHERE division_id = ?", (division_id,))
        matches = c.execute("""
            SELECT home_team_id, away_team_id, home_score, away_score FROM league_matches
            WHERE status='played' AND division_id = ?
        """, (division_id,)).fetchall()
    else:
        c.execute("UPDATE teams SET points=0, played=0, wins=0, draws=0, losses=0, goals_for=0, goals_against=0")
        matches = c.execute("SELECT home_team_id, away_team_id, home_score, away_score FROM league_matches WHERE status='played'").fetchall()

    for m in matches:
        home_id, away_id, home_score, away_score = m
        c.execute("UPDATE teams SET played = played + 1, goals_for = goals_for + ?, goals_against = goals_against + ? WHERE id = ?", (home_score, away_score, home_id))
        c.execute("UPDATE teams SET played = played + 1, goals_for = goals_for + ?, goals_against = goals_against + ? WHERE id = ?", (away_score, home_score, away_id))
        if home_score > away_score:
            c.execute("UPDATE teams SET wins = wins + 1, points = points + 3 WHERE id = ?", (home_id,))
            c.execute("UPDATE teams SET losses = losses + 1 WHERE id = ?", (away_id,))
        elif home_score < away_score:
            c.execute("UPDATE teams SET wins = wins + 1, points = points + 3 WHERE id = ?", (away_id,))
            c.execute("UPDATE teams SET losses = losses + 1 WHERE id = ?", (home_id,))
        else:
            c.execute("UPDATE teams SET draws = draws + 1, points = points + 1 WHERE id = ?", (home_id,))
            c.execute("UPDATE teams SET draws = draws + 1, points = points + 1 WHERE id = ?", (away_id,))

    c.execute("UPDATE teams SET points = points + points_adj")

    conn.commit()
    conn.close()

@app.route("/league")
def league():
    if "user" not in session:
        return redirect(url_for("login"))

    division_id = request.args.get("division_id", type=int)
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    divisions = c.execute("SELECT id, name, match_duration FROM divisions ORDER BY name").fetchall()

    if not division_id:
        today_name = datetime.now().strftime("%A")
        for div in divisions:
            if div[1] == today_name:
                division_id = div[0]
                break

    if division_id:
        update_standings(division_id)
    else:
        update_standings()

    teams = c.execute("""
        SELECT id, name, captain, total_league_fee, points, played, wins, draws, losses, goals_for, goals_against, points_adj
        FROM teams WHERE division_id = ?
        ORDER BY points DESC, (goals_for - goals_against) DESC
    """, (division_id,)).fetchall()

    paid_per_team = {}
    payments = c.execute("SELECT team_id, SUM(amount) FROM league_payments GROUP BY team_id").fetchall()
    for p in payments:
        paid_per_team[p[0]] = p[1]

    enhanced_teams = []
    for t in teams:
        team_id = t[0]
        total_fee = t[3] if t[3] is not None else 0
        paid = paid_per_team.get(team_id, 0)
        balance = total_fee - paid
        enhanced_teams.append({
            "id": team_id,
            "name": t[1],
            "captain": t[2] or "",
            "total_fee": total_fee,
            "paid": paid,
            "balance": balance,
            "points": t[4],
            "played": t[5],
            "wins": t[6],
            "draws": t[7],
            "losses": t[8],
            "goals_for": t[9],
            "goals_against": t[10],
            "points_adj": t[11]
        })

    upcoming = c.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.referee, lm.status, lm.payment_status, b.amount, lm.paid_amount
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'scheduled' AND lm.division_id = ?
        ORDER BY b.date, b.time
    """, (division_id,)).fetchall()

    played = c.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.payment_status, b.amount, lm.paid_amount
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'played' AND lm.division_id = ?
        ORDER BY b.date DESC, b.time DESC
    """, (division_id,)).fetchall()

    conn.close()
    return render_template(
        "league.html",
        divisions=divisions,
        selected_division=division_id,
        teams=enhanced_teams,
        upcoming=upcoming,
        played=played,
        user=session.get("user")
    )

@app.route("/league/update_score", methods=["POST"])
def update_score():
    if "user" not in session:
        return redirect(url_for("login"))
    match_id = request.form["match_id"]
    home_score = int(request.form["home_score"])
    away_score = int(request.form["away_score"])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE league_matches SET home_score=?, away_score=?, status='played' WHERE id=?", (home_score, away_score, match_id))
    match = c.execute("SELECT division_id FROM league_matches WHERE id = ?", (match_id,)).fetchone()

    # Create referee record if referee exists
    match_data = c.execute("SELECT referee, booking_id FROM league_matches WHERE id = ?", (match_id,)).fetchone()
    if match_data and match_data[0]:
        booking = c.execute("SELECT date FROM bookings WHERE id = ?", (match_data[1],)).fetchone()
        if booking:
            existing = c.execute("SELECT id FROM referee_records WHERE match_id = ?", (match_id,)).fetchone()
            if not existing:
                c.execute("""
                    INSERT INTO referee_records (referee_name, match_id, date, fee, paid)
                    VALUES (?, ?, ?, 0, 0)
                """, (match_data[0], match_id, booking[0]))

    conn.commit()
    division_id = match[0] if match else None
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/edit_score/<int:match_id>", methods=["POST"])
def edit_score(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    home_score = int(request.form["home_score"])
    away_score = int(request.form["away_score"])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE league_matches SET home_score=?, away_score=? WHERE id=?", (home_score, away_score, match_id))
    match = c.execute("SELECT division_id FROM league_matches WHERE id = ?", (match_id,)).fetchone()
    conn.commit()
    division_id = match[0] if match else None
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/mark_paid/<int:match_id>", methods=["POST"])
def mark_match_paid(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE league_matches SET payment_status = 'paid' WHERE id = ?", (match_id,))
    match = c.execute("SELECT division_id FROM league_matches WHERE id = ?", (match_id,)).fetchone()
    conn.commit()
    division_id = match[0] if match else None
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/add_team", methods=["POST"])
def add_team():
    if "user" not in session:
        return redirect(url_for("login"))
    name = request.form["name"]
    captain = request.form.get("captain", "")
    total_fee = int(request.form.get("total_fee", 0))
    division_id = int(request.form.get("division_id"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO teams (name, captain, total_league_fee, division_id) VALUES (?, ?, ?, ?)",
                  (name, captain, total_fee, division_id))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/edit_team/<int:team_id>", methods=["POST"])
def edit_team(team_id):
    if "user" not in session:
        return redirect(url_for("login"))
    points_adj = int(request.form.get("points_adj", 0))
    total_fee = int(request.form.get("total_fee", 0))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE teams SET points_adj = ?, total_league_fee = ? WHERE id = ?", (points_adj, total_fee, team_id))
    conn.commit()
    team = c.execute("SELECT division_id FROM teams WHERE id = ?", (team_id,)).fetchone()
    conn.close()
    division_id = team[0] if team else None
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/delete_team/<int:team_id>", methods=["POST"])
def delete_team(team_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    team = c.execute("SELECT division_id FROM teams WHERE id = ?", (team_id,)).fetchone()
    division_id = team[0] if team else None
    c.execute("DELETE FROM teams WHERE id = ?", (team_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/team_payment", methods=["POST"])
def team_payment():
    if "user" not in session:
        return redirect(url_for("login"))
    team_id = request.form["team_id"]
    player_name = request.form["player_name"]
    amount = int(request.form["amount"])
    method = request.form["method"]
    notes = request.form.get("notes", "")
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO league_payments (team_id, player_name, amount, method, date, notes)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (team_id, player_name, amount, method, today, notes))
    team = c.execute("SELECT division_id FROM teams WHERE id = ?", (team_id,)).fetchone()
    conn.commit()
    division_id = team[0] if team else None
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/matches")
def league_matches():
    if "user" not in session:
        return redirect(url_for("login"))
    division_id = request.args.get("division_id", type=int)
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    if division_id:
        matches = c.execute("""
            SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.status, d.name
            FROM league_matches lm
            JOIN bookings b ON lm.booking_id = b.id
            JOIN teams t1 ON lm.home_team_id = t1.id
            JOIN teams t2 ON lm.away_team_id = t2.id
            JOIN divisions d ON lm.division_id = d.id
            WHERE lm.division_id = ?
            ORDER BY b.date DESC, b.time DESC
        """, (division_id,)).fetchall()
    else:
        matches = c.execute("""
            SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.status, d.name
            FROM league_matches lm
            JOIN bookings b ON lm.booking_id = b.id
            JOIN teams t1 ON lm.home_team_id = t1.id
            JOIN teams t2 ON lm.away_team_id = t2.id
            JOIN divisions d ON lm.division_id = d.id
            ORDER BY b.date DESC, b.time DESC
        """).fetchall()
    conn.close()
    return render_template("league_matches.html", matches=matches, user=session.get("user"))

# -----------------------------
# DAILY REPORT
# -----------------------------
@app.route("/daily-report")
def daily_report():
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    other_bookings = c.execute("""
        SELECT id, name, phone, court, time, date, booking_type, amount, paid, duration
        FROM bookings
        WHERE date = ? AND booking_type != 'league'
        ORDER BY time
    """, (date_str,)).fetchall()

    league_matches = c.execute("""
        SELECT lm.id, b.time, t1.name, t2.name, lm.referee, b.amount, lm.paid_amount, lm.payment_status, b.id as booking_id
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE b.date = ?
        ORDER BY b.time
    """, (date_str,)).fetchall()

    social_payments = c.execute("""
        SELECT p.booking_id, p.payer_name, p.amount, p.method, p.date
        FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE b.date = ? AND b.booking_type = 'social'
        ORDER BY p.created_at
    """, (date_str,)).fetchall()

    league_payments = c.execute("""
        SELECT lp.booking_id, lp.player_name, t.name as team_name, lp.amount, lp.method, lp.date
        FROM league_payments lp
        JOIN bookings b ON lp.booking_id = b.id
        JOIN teams t ON lp.team_id = t.id
        WHERE b.date = ?
        ORDER BY lp.created_at
    """, (date_str,)).fetchall()

    expenses = c.execute("""
        SELECT id, supplier, invoice_no, amount, reason, created_at
        FROM expenses
        WHERE date = ?
        ORDER BY created_at
    """, (date_str,)).fetchall()

    staff_on_duty = c.execute("""
        SELECT s.name, sd.shift
        FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = ?
        ORDER BY sd.shift
    """, (date_str,)).fetchall()

    conn.close()

    social_total_amount = sum(b[7] for b in other_bookings if b[6] == 'social') if other_bookings else 0
    social_total_paid = sum(b[8] for b in other_bookings if b[6] == 'social') if other_bookings else 0
    social_total_balance = social_total_amount - social_total_paid
    league_total_amount = sum(m[5] for m in league_matches) if league_matches else 0
    league_total_paid = sum(m[6] for m in league_matches) if league_matches else 0
    league_total_balance = league_total_amount - league_total_paid
    total_expenses = sum(e[3] for e in expenses) if expenses else 0

    return render_template(
        "daily_report.html",
        date=date_str,
        other_bookings=other_bookings,
        league_matches=league_matches,
        social_payments=social_payments,
        league_payments=league_payments,
        expenses=expenses,
        staff_on_duty=staff_on_duty,
        social_total_amount=social_total_amount,
        social_total_paid=social_total_paid,
        social_total_balance=social_total_balance,
        league_total_amount=league_total_amount,
        league_total_paid=league_total_paid,
        league_total_balance=league_total_balance,
        total_expenses=total_expenses,
        user=session.get("user")
    )

@app.route("/api/mark-social-complete/<int:booking_id>", methods=["POST"])
def mark_social_complete(booking_id):
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.form.get("date")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    booking = c.execute("SELECT amount, paid FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    if booking:
        amount_to_pay = booking[0] - booking[1]
        if amount_to_pay > 0:
            c.execute("""
                INSERT INTO payments (booking_id, payer_name, amount, method, date)
                VALUES (?, 'System Complete', ?, 'cash', date('now'))
            """, (booking_id, amount_to_pay))
            c.execute("UPDATE bookings SET paid = amount WHERE id = ?", (booking_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("daily_report", date=date_str))

@app.route("/api/mark-league-complete/<int:match_id>", methods=["POST"])
def mark_league_complete(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.form.get("date")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE league_matches SET payment_status = 'paid' WHERE id = ?", (match_id,))
    match = c.execute("SELECT booking_id FROM league_matches WHERE id = ?", (match_id,)).fetchone()
    if match:
        booking = c.execute("SELECT amount FROM bookings WHERE id = ?", (match[0],)).fetchone()
        if booking:
            c.execute("UPDATE league_matches SET paid_amount = ? WHERE id = ?", (booking[0], match_id))
    conn.commit()
    conn.close()
    return redirect(url_for("daily_report", date=date_str))

# -----------------------------
# STAFF MANAGEMENT
# -----------------------------
@app.route("/staff")
def staff():
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    all_staff = c.execute("SELECT id, name, phone, created_at FROM staff ORDER BY name").fetchall()
    staff_on_duty = c.execute("""
        SELECT sd.id, s.name, sd.shift FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = ?
        ORDER BY sd.shift
    """, (date_str,)).fetchall()
    conn.close()
    return render_template("staff.html", staff=all_staff, staff_on_duty=staff_on_duty, date=date_str, user=session.get("user"))

@app.route("/staff/reports")
def staff_reports():
    if "user" not in session:
        return redirect(url_for("login"))
    from_date = request.args.get("from_date", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date = request.args.get("to_date", datetime.now().strftime("%Y-%m-%d"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    staff_summary = c.execute("""
        SELECT s.id, s.name,
               COUNT(DISTINCT sd.date) as total_days,
               COUNT(sd.id) as total_shifts,
               GROUP_CONCAT(DISTINCT sd.shift) as shifts_types
        FROM staff s
        LEFT JOIN staff_duty sd ON s.id = sd.staff_id AND sd.date BETWEEN ? AND ?
        GROUP BY s.id
        ORDER BY total_shifts DESC
    """, (from_date, to_date)).fetchall()
    staff_shifts = c.execute("""
        SELECT s.name, sd.date, sd.shift
        FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date BETWEEN ? AND ?
        ORDER BY sd.date DESC, s.name
    """, (from_date, to_date)).fetchall()
    conn.close()
    return render_template("staff_reports.html", staff_summary=staff_summary, staff_shifts=staff_shifts, from_date=from_date, to_date=to_date, user=session.get("user"))

@app.route("/api/staff/add", methods=["POST"])
def add_staff():
    if "user" not in session:
        return redirect(url_for("login"))
    name = request.form["name"]
    phone = request.form.get("phone", "")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO staff (name, phone) VALUES (?, ?)", (name, phone))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(url_for("staff"))

@app.route("/api/staff/duty/add", methods=["POST"])
def add_staff_duty():
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.form["date"]
    staff_id = request.form["staff_id"]
    shift = request.form["shift"]
    hours = int(request.form.get("hours", 8))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO staff_duty (date, staff_id, shift) VALUES (?, ?, ?)", (date_str, staff_id, shift))
    c.execute("""
        INSERT OR REPLACE INTO staff_shift_records (staff_id, date, shift, hours_worked)
        VALUES (?, ?, ?, ?)
    """, (staff_id, date_str, shift, hours))
    conn.commit()
    conn.close()
    return redirect(url_for("staff", date=date_str))

@app.route("/api/staff/duty/remove/<int:duty_id>", methods=["POST"])
def remove_staff_duty(duty_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    duty = c.execute("SELECT date, staff_id, shift FROM staff_duty WHERE id = ?", (duty_id,)).fetchone()
    date_str = duty[0] if duty else None
    if duty:
        c.execute("DELETE FROM staff_duty WHERE id = ?", (duty_id,))
        c.execute("DELETE FROM staff_shift_records WHERE staff_id = ? AND date = ? AND shift = ?", (duty[1], duty[0], duty[2]))
        conn.commit()
    conn.close()
    return redirect(url_for("staff", date=date_str))

# -----------------------------
# REFEREE REPORTS
# -----------------------------
@app.route("/referee/reports")
def referee_reports():
    if "user" not in session:
        return redirect(url_for("login"))
    from_date = request.args.get("from_date", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date = request.args.get("to_date", datetime.now().strftime("%Y-%m-%d"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    referee_summary = c.execute("""
        SELECT referee_name,
               COUNT(*) as total_games,
               SUM(fee) as total_fees,
               SUM(paid) as total_paid,
               (SUM(fee) - SUM(paid)) as balance
        FROM referee_records
        WHERE date BETWEEN ? AND ?
        GROUP BY referee_name
        ORDER BY total_games DESC
    """, (from_date, to_date)).fetchall()
    referee_games = c.execute("""
        SELECT rr.id, rr.referee_name, rr.date,
               t1.name as home_team, t2.name as away_team,
               rr.fee, rr.paid
        FROM referee_records rr
        JOIN league_matches lm ON rr.match_id = lm.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE rr.date BETWEEN ? AND ?
        ORDER BY rr.date DESC, rr.referee_name
    """, (from_date, to_date)).fetchall()
    conn.close()
    return render_template("referee_reports.html", referee_summary=referee_summary, referee_games=referee_games, from_date=from_date, to_date=to_date, user=session.get("user"))

@app.route("/api/referee/update_fee", methods=["POST"])
def update_referee_fee():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    record_id = request.form["record_id"]
    fee = int(request.form["fee"])
    from_date = request.form.get("from_date")
    to_date = request.form.get("to_date")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE referee_records SET fee = ? WHERE id = ?", (fee, record_id))
    conn.commit()
    conn.close()
    return redirect(url_for("referee_reports", from_date=from_date, to_date=to_date))

@app.route("/api/referee/mark_paid", methods=["POST"])
def mark_referee_paid():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    record_id = request.form["record_id"]
    from_date = request.form.get("from_date")
    to_date = request.form.get("to_date")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE referee_records SET paid = fee WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return redirect(url_for("referee_reports", from_date=from_date, to_date=to_date))

# -----------------------------
# CASH MANAGEMENT
# -----------------------------
def get_cash_summary(date_str):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    cash_day = c.execute("SELECT start_cash, counted_cash FROM cash_days WHERE date = ?", (date_str,)).fetchone()
    start_cash = cash_day[0] if cash_day else 0
    counted_cash = cash_day[1] if cash_day else 0
    social_cash = c.execute("""
        SELECT SUM(p.amount) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'cash' AND p.date = ? AND b.booking_type = 'social'
    """, (date_str,)).fetchone()[0] or 0
    league_cash = c.execute("""
        SELECT SUM(amount) FROM league_payments
        WHERE method = 'cash' AND date = ?
    """, (date_str,)).fetchone()[0] or 0
    total_cash_income = social_cash + league_cash
    expenses = c.execute("""
        SELECT id, supplier, invoice_no, amount, reason, created_at FROM expenses
        WHERE date = ?
        ORDER BY created_at
    """, (date_str,)).fetchall()
    total_expenses = sum(e[3] for e in expenses) if expenses else 0
    expected_cash = start_cash + total_cash_income - total_expenses
    conn.close()
    return {
        "start_cash": start_cash,
        "counted_cash": counted_cash,
        "total_cash_income": total_cash_income,
        "total_expenses": total_expenses,
        "expected_cash": expected_cash,
        "expenses": [{"id": e[0], "supplier": e[1], "invoice_no": e[2], "amount": e[3], "reason": e[4], "date": e[5]} for e in expenses]
    }

@app.route("/cash")
def cash_page():
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.args.get("date", datetime.now().strftime("%Y-%m-%d"))
    summary = get_cash_summary(date_str)
    return render_template("cash.html", date=date_str, summary=summary, user=session.get("user"))

@app.route("/api/cash/start", methods=["POST"])
def set_start_cash():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    date_str = request.form["date"]
    start_cash = int(request.form["start_cash"])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("INSERT OR REPLACE INTO cash_days (date, start_cash) VALUES (?, ?)", (date_str, start_cash))
    conn.commit()
    conn.close()
    return redirect(url_for("cash_page", date=date_str))

@app.route("/api/cash/count", methods=["POST"])
def record_cash_count():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    date_str = request.form["date"]
    counted_cash = int(request.form["counted_cash"])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE cash_days SET counted_cash = ?, counted_at = CURRENT_TIMESTAMP WHERE date = ?", (counted_cash, date_str))
    if c.rowcount == 0:
        c.execute("INSERT INTO cash_days (date, counted_cash, counted_at) VALUES (?, ?, CURRENT_TIMESTAMP)", (date_str, counted_cash))
    conn.commit()
    conn.close()
    return redirect(url_for("cash_page", date=date_str))

@app.route("/api/expenses/add", methods=["POST"])
def add_expense():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    date_str = request.form["date"]
    supplier = request.form["supplier"]
    invoice_no = request.form["invoice_no"]
    amount = int(request.form["amount"])
    reason = request.form["reason"]
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO expenses (date, supplier, invoice_no, amount, reason)
        VALUES (?, ?, ?, ?, ?)
    """, (date_str, supplier, invoice_no, amount, reason))
    conn.commit()
    conn.close()
    return redirect(url_for("cash_page", date=date_str))

@app.route("/api/expenses/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    exp = c.execute("SELECT date FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    if exp:
        c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        conn.commit()
        conn.close()
        return redirect(url_for("cash_page", date=exp[0]))
    conn.close()
    return redirect(url_for("cash_page"))

# -----------------------------
# REPORTS, ANALYTICS, WHATSAPP
# -----------------------------
@app.route("/reports")
def reports():
    if "user" not in session:
        return redirect(url_for("login"))
    return render_template("reports.html", user=session.get("user"))

@app.route("/analytics")
def analytics():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    daily_revenue = c.execute("""
        SELECT date, SUM(amount) FROM payments
        WHERE date >= ?
        GROUP BY date
        ORDER BY date
    """, (thirty_days_ago,)).fetchall()
    weekly_revenue = c.execute("""
        SELECT strftime('%Y-%W', date) as week, SUM(amount)
        FROM payments
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """).fetchall()
    method_breakdown = c.execute("""
        SELECT method, SUM(amount) FROM payments GROUP BY method
    """).fetchall()
    conn.close()
    return render_template(
        "analytics.html",
        daily_revenue=daily_revenue,
        weekly_revenue=weekly_revenue,
        method_breakdown=method_breakdown,
        user=session.get("user")
    )

@app.route("/export/bookings")
def export_bookings():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    bookings = c.execute("SELECT * FROM bookings ORDER BY date DESC, time").fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Name", "Phone", "Court", "Time", "Date", "Type", "Amount", "Paid", "Duration"])
    for b in bookings:
        writer.writerow([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[9]])
    response = make_response(output.getvalue())
    response.headers["Content-Disposition"] = "attachment; filename=bookings_export.csv"
    response.headers["Content-type"] = "text/csv"
    return response

@app.route("/whatsapp/<int:booking_id>")
def whatsapp_reminder(booking_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    booking = c.execute("SELECT name, phone, court, time, date FROM bookings WHERE id=?", (booking_id,)).fetchone()
    conn.close()
    if not booking:
        return "Booking not found", 404
    name, phone, court, time, date = booking
    message = f"Hi {name}, reminder: Your booking at {court} on {date} at {time}. Please confirm or pay if not done yet. Fives System"
    import urllib.parse
    encoded_message = urllib.parse.quote(message)
    wa_link = f"https://wa.me/{phone}?text={encoded_message}"
    return redirect(wa_link)

@app.route("/api/monthly-summary")
def monthly_summary():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    rows = c.execute("""
        SELECT strftime('%Y-%m', date) as month,
               COUNT(*) as count,
               SUM(amount) as total,
               SUM(paid) as paid
        FROM bookings
        GROUP BY month
        ORDER BY month DESC
    """).fetchall()
    conn.close()
    result = [{"month": r[0], "count": r[1], "total": r[2], "paid": r[3]} for r in rows]
    return jsonify(result)

@app.route("/api/analytics-data")
def analytics_data():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    daily_revenue = c.execute("""
        SELECT date, SUM(amount) FROM payments
        WHERE date >= ?
        GROUP BY date
        ORDER BY date
    """, (thirty_days_ago,)).fetchall()
    weekly_revenue = c.execute("""
        SELECT strftime('%Y-%W', date) as week, SUM(amount)
        FROM payments
        GROUP BY week
        ORDER BY week DESC
        LIMIT 12
    """).fetchall()
    method_breakdown = c.execute("""
        SELECT method, SUM(amount) FROM payments GROUP BY method
    """).fetchall()
    conn.close()
    return jsonify({
        "daily": [{"date": d[0], "revenue": d[1]} for d in daily_revenue],
        "weekly": [{"week": w[0], "revenue": w[1]} for w in weekly_revenue],
        "methods": [{"method": m[0], "total": m[1]} for m in method_breakdown]
    })

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0')