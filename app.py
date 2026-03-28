from flask import Flask, render_template, request, redirect, session, url_for, jsonify, make_response
import sqlite3
from datetime import datetime, timedelta
import traceback
import csv
import io

app = Flask(__name__)
app.secret_key = "your-secret-key-change-in-production"

# -----------------------------
# DATABASE INITIALISATION (unchanged)
# -----------------------------
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
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
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
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
    c.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE,
            points INTEGER DEFAULT 0,
            played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            goals_for INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS league_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            booking_id INTEGER,
            home_team_id INTEGER,
            away_team_id INTEGER,
            home_score INTEGER DEFAULT 0,
            away_score INTEGER DEFAULT 0,
            referee TEXT,
            status TEXT DEFAULT 'scheduled',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (booking_id) REFERENCES bookings (id),
            FOREIGN KEY (home_team_id) REFERENCES teams (id),
            FOREIGN KEY (away_team_id) REFERENCES teams (id)
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS league_payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            team_id INTEGER,
            amount INTEGER,
            method TEXT,
            date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (team_id) REFERENCES teams (id)
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
# DASHBOARD (unchanged, times 06:00-23:00)
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
        time = b[4]
        court = b[3]
        schedule[time][court] = b

    if bookings:
        total_bookings = len(bookings)
        total_amount = sum(int(b[7]) for b in bookings)
        total_paid = sum(int(b[8]) for b in bookings)
        total_outstanding = total_amount - total_paid
    else:
        total_bookings = 0
        total_amount = 0
        total_paid = 0
        total_outstanding = 0

    all_payments = c.execute("SELECT SUM(amount) FROM payments").fetchone()[0] or 0
    all_bookings = c.execute("SELECT COUNT(*) FROM bookings").fetchone()[0] or 0

    conn.close()

    return render_template(
        "dashboard.html",
        schedule=schedule,
        times=times,
        courts=courts,
        today=today,
        user=session.get("user"),
        error=request.args.get("error"),
        total_bookings_day=total_bookings,
        total_amount_day=total_amount,
        total_paid_day=total_paid,
        total_outstanding_day=total_outstanding,
        all_revenue=all_payments,
        all_bookings=all_bookings
    )

# -----------------------------
# ADD BOOKING (unchanged)
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
    amount = int(request.form["amount"])
    today = datetime.now().strftime("%Y-%m-%d")

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    existing = c.execute(
        "SELECT id FROM bookings WHERE court = ? AND time = ? AND date = ?",
        (court, time, today)
    ).fetchone()
    if existing:
        conn.close()
        return redirect(url_for("dashboard", error="Slot already booked"))

    c.execute("""
        INSERT INTO bookings (name, phone, court, time, date, booking_type, amount, paid)
        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
    """, (name, phone, court, time, today, booking_type, amount))
    booking_id = c.lastrowid

    if booking_type == "league":
        home_team_id = request.form.get("home_team_id")
        away_team_id = request.form.get("away_team_id")
        referee = request.form.get("referee", "")
        if home_team_id and away_team_id:
            c.execute("""
                INSERT INTO league_matches (booking_id, home_team_id, away_team_id, referee, status)
                VALUES (?, ?, ?, ?, 'scheduled')
            """, (booking_id, home_team_id, away_team_id, referee))

    conn.commit()
    conn.close()
    return redirect(url_for("dashboard"))

# -----------------------------
# RECORD PAYMENT (handles both social and league)
# -----------------------------
@app.route("/payment/<int:booking_id>", methods=["POST"])
def record_payment(booking_id):
    if "user" not in session:
        return redirect(url_for("login"))

    # Determine booking type
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
            # Social payment: record in payments table
            payer_name = request.form["payer_name"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            c.execute("""
                INSERT INTO payments (booking_id, payer_name, amount, method, date)
                VALUES (?, ?, ?, ?, ?)
            """, (booking_id, payer_name, amount, method, today))
            c.execute("UPDATE bookings SET paid = paid + ? WHERE id = ?", (amount, booking_id))
        else:  # league payment: record in league_payments with team_id
            team_id = request.form["team_id"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            notes = request.form.get("notes", "")  # optional notes
            c.execute("""
                INSERT INTO league_payments (team_id, amount, method, date, notes)
                VALUES (?, ?, ?, ?, ?)
            """, (team_id, amount, method, today, notes))
            # Also update the booking's paid amount? In league, the payment is for the team,
            # not necessarily for the booking. But you might still want to track that the booking
            # has received a payment. If you want to track payments against the booking,
            # uncomment the line below. I'll leave it optional.
            # c.execute("UPDATE bookings SET paid = paid + ? WHERE id = ?", (amount, booking_id))

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
# VIEW ALL BOOKINGS (unchanged)
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
# AJAX: GET PAYMENTS FOR A BOOKING (social payments only)
# -----------------------------
@app.route("/api/payments/<int:booking_id>")
def get_payments(booking_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    payments = c.execute(
        "SELECT payer_name, amount, method, date FROM payments WHERE booking_id = ? ORDER BY created_at",
        (booking_id,)
    ).fetchall()
    conn.close()

    payments_list = [{"payer": p[0], "amount": p[1], "method": p[2], "date": p[3]} for p in payments]
    return jsonify(payments_list)

# -----------------------------
# AJAX: GET BOOKING DETAILS (includes booking_type)
# -----------------------------
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

# -----------------------------
# AJAX: GET TEAMS (for league payment dropdown)
# -----------------------------
@app.route("/api/teams")
def api_teams():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    teams = c.execute("SELECT id, name FROM teams ORDER BY name").fetchall()
    conn.close()
    return jsonify([{"id": t[0], "name": t[1]} for t in teams])

# -----------------------------
# LEAGUE MANAGEMENT (unchanged)
# -----------------------------
def update_standings():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
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
    conn.commit()
    conn.close()

@app.route("/league")
def league():
    if "user" not in session:
        return redirect(url_for("login"))

    update_standings()

    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    teams = c.execute("""
        SELECT id, name, points, played, wins, draws, losses, goals_for, goals_against
        FROM teams ORDER BY points DESC, (goals_for - goals_against) DESC
    """).fetchall()

    upcoming = c.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.referee
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'scheduled'
        ORDER BY b.date, b.time
    """).fetchall()

    played = c.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'played'
        ORDER BY b.date DESC, b.time DESC
    """).fetchall()

    payments = c.execute("""
        SELECT t.name, SUM(lp.amount) as total_paid
        FROM league_payments lp
        JOIN teams t ON lp.team_id = t.id
        GROUP BY t.id
    """).fetchall()

    conn.close()
    return render_template("league.html", teams=teams, upcoming=upcoming, played=played, payments=payments, user=session.get("user"))

@app.route("/league/add_team", methods=["POST"])
def add_team():
    if "user" not in session:
        return redirect(url_for("login"))
    name = request.form["name"]
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    try:
        c.execute("INSERT INTO teams (name) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()
    return redirect(url_for("league"))

@app.route("/league/record_result", methods=["POST"])
def record_result():
    if "user" not in session:
        return redirect(url_for("login"))
    match_id = request.form["match_id"]
    home_score = int(request.form["home_score"])
    away_score = int(request.form["away_score"])
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("UPDATE league_matches SET home_score=?, away_score=?, status='played' WHERE id=?", (home_score, away_score, match_id))
    conn.commit()
    conn.close()
    return redirect(url_for("league"))

@app.route("/league/team_payment", methods=["POST"])
def team_payment():
    if "user" not in session:
        return redirect(url_for("login"))
    team_id = request.form["team_id"]
    amount = int(request.form["amount"])
    method = request.form["method"]
    notes = request.form.get("notes", "")
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    c.execute("""
        INSERT INTO league_payments (team_id, amount, method, date, notes)
        VALUES (?, ?, ?, ?, ?)
    """, (team_id, amount, method, today, notes))
    conn.commit()
    conn.close()
    return redirect(url_for("league"))

@app.route("/league/matches")
def league_matches():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = sqlite3.connect("database.db")
    c = conn.cursor()
    matches = c.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.status
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        ORDER BY b.date DESC, b.time DESC
    """).fetchall()
    conn.close()
    return render_template("league_matches.html", matches=matches, user=session.get("user"))

# =========================
# PHASE 4: REPORTS, ANALYTICS, WHATSAPP
# =========================

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
    writer.writerow(["ID", "Name", "Phone", "Court", "Time", "Date", "Type", "Amount", "Paid", "Balance"])
    for b in bookings:
        writer.writerow([b[0], b[1], b[2], b[3], b[4], b[5], b[6], b[7], b[8], b[7]-b[8]])

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
    app.run(debug=True)