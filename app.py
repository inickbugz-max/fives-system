import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, session, url_for, jsonify, make_response
from datetime import datetime, timedelta
import traceback
import csv
import io

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'your-secret-key-change-in-production')

# -----------------------------
# DATABASE CONNECTION
# -----------------------------
def get_db_connection():
    database_url = os.environ.get('DATABASE_URL')
    if not database_url:
        raise Exception("DATABASE_URL environment variable not set!")
    if database_url.startswith('postgres://'):
        database_url = database_url.replace('postgres://', 'postgresql://', 1)
    conn = psycopg2.connect(database_url)
    return conn

# -----------------------------
# DATABASE INITIALISATION
# -----------------------------
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()

    # Bookings table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id SERIAL PRIMARY KEY,
            name TEXT,
            phone TEXT,
            court TEXT,
            time TEXT,
            date TEXT,
            booking_type TEXT,
            amount INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            duration INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Social payments table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id),
            payer_name TEXT,
            amount INTEGER,
            method TEXT,
            date TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Divisions table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS divisions (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            match_duration INTEGER DEFAULT 45,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Insert default divisions
    default_divisions = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    for div in default_divisions:
        cur.execute("INSERT INTO divisions (name) VALUES (%s) ON CONFLICT (name) DO NOTHING", (div,))

    # Teams table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS teams (
            id SERIAL PRIMARY KEY,
            name TEXT,
            captain TEXT,
            total_league_fee INTEGER DEFAULT 0,
            division_id INTEGER REFERENCES divisions(id),
            points INTEGER DEFAULT 0,
            points_adj INTEGER DEFAULT 0,
            played INTEGER DEFAULT 0,
            wins INTEGER DEFAULT 0,
            draws INTEGER DEFAULT 0,
            losses INTEGER DEFAULT 0,
            goals_for INTEGER DEFAULT 0,
            goals_against INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(name, division_id)
        )
    """)

    # League matches table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_matches (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id),
            division_id INTEGER REFERENCES divisions(id),
            home_team_id INTEGER REFERENCES teams(id),
            away_team_id INTEGER REFERENCES teams(id),
            home_score INTEGER DEFAULT 0,
            away_score INTEGER DEFAULT 0,
            referee TEXT,
            status TEXT DEFAULT 'scheduled',
            payment_status TEXT DEFAULT 'unpaid',
            paid_amount INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # League payments table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS league_payments (
            id SERIAL PRIMARY KEY,
            booking_id INTEGER REFERENCES bookings(id),
            team_id INTEGER REFERENCES teams(id),
            player_name TEXT,
            amount INTEGER,
            method TEXT,
            date TEXT,
            notes TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Cash days table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cash_days (
            id SERIAL PRIMARY KEY,
            date TEXT UNIQUE,
            start_cash INTEGER DEFAULT 0,
            counted_cash INTEGER DEFAULT 0,
            counted_at TIMESTAMP
        )
    """)

    # Expenses table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses (
            id SERIAL PRIMARY KEY,
            date TEXT,
            supplier TEXT,
            invoice_no TEXT,
            amount INTEGER,
            reason TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staff table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff (
            id SERIAL PRIMARY KEY,
            name TEXT UNIQUE,
            phone TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staff duty records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff_duty (
            id SERIAL PRIMARY KEY,
            date TEXT,
            staff_id INTEGER REFERENCES staff(id),
            shift TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Staff shift records
    cur.execute("""
        CREATE TABLE IF NOT EXISTS staff_shift_records (
            id SERIAL PRIMARY KEY,
            staff_id INTEGER REFERENCES staff(id),
            date TEXT,
            shift TEXT,
            hours_worked INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(staff_id, date, shift)
        )
    """)

    # Referee records table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS referee_records (
            id SERIAL PRIMARY KEY,
            referee_name TEXT,
            match_id INTEGER REFERENCES league_matches(id),
            date TEXT,
            fee INTEGER DEFAULT 0,
            paid INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    conn.commit()
    cur.close()
    conn.close()

# Initialize database on startup (if tables don't exist)
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

    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT * FROM bookings WHERE date = %s ORDER BY time, court", (today,))
    bookings = cur.fetchall()

    schedule = {}
    for t in times:
        schedule[t] = {}
        for c_name in courts:
            schedule[t][c_name] = None
    for b in bookings:
        schedule[b[4]][b[3]] = b   # b[4]=time, b[3]=court

    total_bookings_day = len(bookings)
    total_amount_day = sum(b[7] for b in bookings if b[7]) if bookings else 0
    total_paid_day = sum(b[8] for b in bookings if b[8]) if bookings else 0
    total_outstanding_day = total_amount_day - total_paid_day

    cur.execute("SELECT COALESCE(SUM(amount),0) FROM payments")
    all_payments = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM bookings")
    all_bookings = cur.fetchone()[0]

    # Payment breakdown
    cur.execute("""
        SELECT COALESCE(SUM(p.amount),0) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'cash' AND b.booking_type = 'social'
    """)
    social_cash = cur.fetchone()[0]
    cur.execute("""
        SELECT COALESCE(SUM(p.amount),0) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'card' AND b.booking_type = 'social'
    """)
    social_card = cur.fetchone()[0]
    cur.execute("""
        SELECT COALESCE(SUM(p.amount),0) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'eft' AND b.booking_type = 'social'
    """)
    social_eft = cur.fetchone()[0]

    cur.execute("SELECT COALESCE(SUM(amount),0) FROM league_payments WHERE method = 'cash'")
    league_cash = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM league_payments WHERE method = 'card'")
    league_card = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM league_payments WHERE method = 'eft'")
    league_eft = cur.fetchone()[0]

    social_total = social_cash + social_card + social_eft
    league_total = league_cash + league_card + league_eft
    total_cash = social_cash + league_cash
    total_card = social_card + league_card
    total_eft = social_eft + league_eft
    total_all_payments = total_cash + total_card + total_eft

    cur.execute("SELECT COALESCE(SUM(amount),0) FROM expenses WHERE date = %s", (today,))
    today_expenses = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(amount),0) FROM (
            SELECT p.amount FROM payments p
            JOIN bookings b ON p.booking_id = b.id
            WHERE p.method = 'cash' AND p.date = %s
            UNION ALL
            SELECT amount FROM league_payments WHERE method = 'cash' AND date = %s
        ) AS t
    """, (today, today))
    today_cash_income = cur.fetchone()[0]

    cur.execute("SELECT start_cash FROM cash_days WHERE date = %s", (today,))
    start_cash_row = cur.fetchone()
    start_cash = start_cash_row[0] if start_cash_row else 0
    final_cash = start_cash + today_cash_income - today_expenses

    cur.execute("""
        SELECT s.name, sd.shift FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = %s
        ORDER BY sd.shift
    """, (today,))
    staff_on_duty = cur.fetchall()

    cur.close()
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

    conn = get_db_connection()
    cur = conn.cursor()

    start_hour = int(time.split(':')[0])
    conflict = False
    for i in range(duration):
        slot_hour = start_hour + i
        if slot_hour > 23:
            conflict = True
            break
        slot_time = f"{slot_hour:02d}:00"
        cur.execute("SELECT id FROM bookings WHERE court = %s AND time = %s AND date = %s", (court, slot_time, today))
        if cur.fetchone():
            conflict = True
            break

    if conflict:
        cur.close()
        conn.close()
        return redirect(url_for("dashboard", error="Time slot(s) not available for full duration"))

    booking_ids = []
    for i in range(duration):
        slot_hour = start_hour + i
        slot_time = f"{slot_hour:02d}:00"
        cur.execute("""
            INSERT INTO bookings (name, phone, court, time, date, booking_type, amount, paid, duration)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 0, %s) RETURNING id
        """, (name, phone, court, slot_time, today, booking_type, amount, duration))
        booking_id = cur.fetchone()[0]
        booking_ids.append(booking_id)

    if booking_type == "league":
        division_id = request.form.get("division_id")
        home_team_id = request.form.get("home_team_id")
        away_team_id = request.form.get("away_team_id")
        referee = request.form.get("referee", "")
        if division_id and home_team_id and away_team_id:
            cur.execute("""
                INSERT INTO league_matches (booking_id, division_id, home_team_id, away_team_id, referee, status, payment_status, paid_amount)
                VALUES (%s, %s, %s, %s, %s, 'scheduled', 'unpaid', 0)
            """, (booking_ids[0], division_id, home_team_id, away_team_id, referee))

    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("dashboard"))

# -----------------------------
# RECORD PAYMENT
# -----------------------------
@app.route("/payment/<int:booking_id>", methods=["POST"])
def record_payment(booking_id):
    if "user" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT booking_type FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()
    if not booking:
        cur.close()
        conn.close()
        return "Booking not found", 404

    booking_type = booking[0]
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        if booking_type == "social":
            payer_name = request.form["payer_name"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            cur.execute("""
                INSERT INTO payments (booking_id, payer_name, amount, method, date)
                VALUES (%s, %s, %s, %s, %s)
            """, (booking_id, payer_name, amount, method, today))
            cur.execute("UPDATE bookings SET paid = paid + %s WHERE id = %s", (amount, booking_id))
        elif booking_type == "league":
            team_id = request.form["team_id"]
            player_name = request.form["player_name"]
            amount = int(request.form["amount"])
            method = request.form["method"]
            notes = request.form.get("notes", "")
            cur.execute("""
                INSERT INTO league_payments (booking_id, team_id, player_name, amount, method, date, notes)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """, (booking_id, team_id, player_name, amount, method, today, notes))
            cur.execute("""
                UPDATE league_matches 
                SET paid_amount = paid_amount + %s, 
                    payment_status = CASE WHEN paid_amount + %s >= (SELECT amount FROM bookings WHERE id = %s) THEN 'paid' ELSE 'partial' END
                WHERE booking_id = %s
            """, (amount, amount, booking_id, booking_id))

        conn.commit()
        cur.close()
        conn.close()

        referer = request.headers.get("Referer")
        if referer:
            return redirect(referer)
        return redirect(url_for("dashboard"))
    except Exception as e:
        conn.rollback()
        cur.close()
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

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY date DESC, time")
    bookings = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("bookings.html", bookings=bookings, user=session.get("user"))

# -----------------------------
# AJAX ENDPOINTS
# -----------------------------
@app.route("/api/payments/<int:booking_id>")
def get_payments(booking_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT payer_name, amount, method, date, 'social' as type, NULL as team_name
        FROM payments
        WHERE booking_id = %s
        ORDER BY created_at
    """, (booking_id,))
    social_payments = cur.fetchall()
    cur.execute("""
        SELECT lp.player_name, lp.amount, lp.method, lp.date, 'league' as type, t.name as team_name
        FROM league_payments lp
        JOIN teams t ON lp.team_id = t.id
        WHERE lp.booking_id = %s
        ORDER BY lp.created_at
    """, (booking_id,))
    league_payments = cur.fetchall()
    cur.close()
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

    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, amount, paid, booking_type FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    if division_id:
        cur.execute("SELECT id, name FROM teams WHERE division_id = %s ORDER BY name", (division_id,))
    else:
        cur.execute("SELECT id, name FROM teams ORDER BY name")
    teams = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{"id": t[0], "name": t[1]} for t in teams])

@app.route("/api/divisions")
def api_divisions():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, match_duration FROM divisions ORDER BY name")
    divisions = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify([{"id": d[0], "name": d[1], "duration": d[2]} for d in divisions])

# -----------------------------
# LEAGUE MANAGEMENT
# -----------------------------
def update_standings(division_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    if division_id:
        cur.execute("UPDATE teams SET points=0, played=0, wins=0, draws=0, losses=0, goals_for=0, goals_against=0 WHERE division_id = %s", (division_id,))
        cur.execute("""
            SELECT home_team_id, away_team_id, home_score, away_score FROM league_matches 
            WHERE status='played' AND division_id = %s
        """, (division_id,))
    else:
        cur.execute("UPDATE teams SET points=0, played=0, wins=0, draws=0, losses=0, goals_for=0, goals_against=0")
        cur.execute("SELECT home_team_id, away_team_id, home_score, away_score FROM league_matches WHERE status='played'")
    matches = cur.fetchall()
    for m in matches:
        home_id, away_id, home_score, away_score = m
        cur.execute("UPDATE teams SET played = played + 1, goals_for = goals_for + %s, goals_against = goals_against + %s WHERE id = %s", (home_score, away_score, home_id))
        cur.execute("UPDATE teams SET played = played + 1, goals_for = goals_for + %s, goals_against = goals_against + %s WHERE id = %s", (away_score, home_score, away_id))
        if home_score > away_score:
            cur.execute("UPDATE teams SET wins = wins + 1, points = points + 3 WHERE id = %s", (home_id,))
            cur.execute("UPDATE teams SET losses = losses + 1 WHERE id = %s", (away_id,))
        elif home_score < away_score:
            cur.execute("UPDATE teams SET wins = wins + 1, points = points + 3 WHERE id = %s", (away_id,))
            cur.execute("UPDATE teams SET losses = losses + 1 WHERE id = %s", (home_id,))
        else:
            cur.execute("UPDATE teams SET draws = draws + 1, points = points + 1 WHERE id = %s", (home_id,))
            cur.execute("UPDATE teams SET draws = draws + 1, points = points + 1 WHERE id = %s", (away_id,))
    cur.execute("UPDATE teams SET points = points + points_adj")
    conn.commit()
    cur.close()
    conn.close()

@app.route("/league")
def league():
    if "user" not in session:
        return redirect(url_for("login"))

    division_id = request.args.get("division_id", type=int)
    conn = get_db_connection()
    cur = conn.cursor()

    cur.execute("SELECT id, name, match_duration FROM divisions ORDER BY name")
    divisions = cur.fetchall()

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

    cur.execute("""
        SELECT id, name, captain, total_league_fee, points, played, wins, draws, losses, goals_for, goals_against, points_adj
        FROM teams WHERE division_id = %s 
        ORDER BY points DESC, (goals_for - goals_against) DESC
    """, (division_id,))
    teams = cur.fetchall()

    cur.execute("SELECT team_id, SUM(amount) FROM league_payments GROUP BY team_id")
    payments = cur.fetchall()
    paid_per_team = {p[0]: p[1] for p in payments}

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

    cur.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.referee, lm.status, lm.payment_status, b.amount, lm.paid_amount
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'scheduled' AND lm.division_id = %s
        ORDER BY b.date, b.time
    """, (division_id,))
    upcoming = cur.fetchall()

    cur.execute("""
        SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.payment_status, b.amount, lm.paid_amount
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE lm.status = 'played' AND lm.division_id = %s
        ORDER BY b.date DESC, b.time DESC
    """, (division_id,))
    played = cur.fetchall()

    cur.execute("""
        SELECT lp.id, t.name, t.id as team_id, lp.player_name, lp.amount, lp.method, lp.date, lp.notes
        FROM league_payments lp
        JOIN teams t ON lp.team_id = t.id
        ORDER BY t.name, lp.date DESC
    """)
    all_payments = cur.fetchall()
    payments_by_team = {}
    for p in all_payments:
        team_id = p[2]
        team_name = p[1]
        if team_id not in payments_by_team:
            payments_by_team[team_id] = {"team_name": team_name, "payments": []}
        payments_by_team[team_id]["payments"].append({
            "id": p[0],
            "player_name": p[3],
            "amount": p[4],
            "method": p[5],
            "date": p[6],
            "notes": p[7]
        })

    cur.close()
    conn.close()
    return render_template(
        "league.html",
        divisions=divisions,
        selected_division=division_id,
        teams=enhanced_teams,
        upcoming=upcoming,
        played=played,
        payments_by_team=payments_by_team,
        user=session.get("user")
    )

@app.route("/league/add_team", methods=["POST"])
def add_team():
    if "user" not in session:
        return redirect(url_for("login"))
    name = request.form["name"]
    captain = request.form.get("captain", "")
    total_fee = int(request.form.get("total_fee", 0))
    division_id = int(request.form.get("division_id"))
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO teams (name, captain, total_league_fee, division_id) VALUES (%s, %s, %s, %s)",
                    (name, captain, total_fee, division_id))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/edit_team/<int:team_id>", methods=["POST"])
def edit_team(team_id):
    if "user" not in session:
        return redirect(url_for("login"))
    points_adj = int(request.form.get("points_adj", 0))
    total_fee = int(request.form.get("total_fee", 0))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE teams SET points_adj = %s, total_league_fee = %s WHERE id = %s", (points_adj, total_fee, team_id))
    conn.commit()
    cur.execute("SELECT division_id FROM teams WHERE id = %s", (team_id,))
    division_id = cur.fetchone()[0]
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/delete_team/<int:team_id>", methods=["POST"])
def delete_team(team_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT division_id FROM teams WHERE id = %s", (team_id,))
    division_id = cur.fetchone()[0]
    cur.execute("DELETE FROM teams WHERE id = %s", (team_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/record_result", methods=["POST"])
def record_result():
    if "user" not in session:
        return redirect(url_for("login"))
    match_id = request.form["match_id"]
    home_score = int(request.form["home_score"])
    away_score = int(request.form["away_score"])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE league_matches SET home_score = %s, away_score = %s, status = 'played' WHERE id = %s", (home_score, away_score, match_id))
    cur.execute("SELECT division_id, referee, date FROM league_matches WHERE id = %s", (match_id,))
    match = cur.fetchone()
    if match and match[1]:
        referee_name = match[1]
        match_date = match[2] if match[2] else datetime.now().strftime("%Y-%m-%d")
        cur.execute("SELECT id FROM referee_records WHERE match_id = %s", (match_id,))
        existing = cur.fetchone()
        if not existing:
            cur.execute("INSERT INTO referee_records (referee_name, match_id, date, fee, paid) VALUES (%s, %s, %s, 0, 0)",
                        (referee_name, match_id, match_date))
    conn.commit()
    division_id = match[0] if match else None
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/edit_score/<int:match_id>", methods=["POST"])
def edit_score(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    home_score = int(request.form["home_score"])
    away_score = int(request.form["away_score"])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE league_matches SET home_score = %s, away_score = %s WHERE id = %s", (home_score, away_score, match_id))
    cur.execute("SELECT division_id FROM league_matches WHERE id = %s", (match_id,))
    division_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/mark_paid/<int:match_id>", methods=["POST"])
def mark_match_paid(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE league_matches SET payment_status = 'paid' WHERE id = %s", (match_id,))
    cur.execute("SELECT division_id FROM league_matches WHERE id = %s", (match_id,))
    division_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO league_payments (team_id, player_name, amount, method, date, notes)
        VALUES (%s, %s, %s, %s, %s, %s)
    """, (team_id, player_name, amount, method, today, notes))
    cur.execute("SELECT division_id FROM teams WHERE id = %s", (team_id,))
    division_id = cur.fetchone()[0]
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("league", division_id=division_id))

@app.route("/league/matches")
def league_matches():
    if "user" not in session:
        return redirect(url_for("login"))
    division_id = request.args.get("division_id", type=int)
    conn = get_db_connection()
    cur = conn.cursor()
    if division_id:
        cur.execute("""
            SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.status, d.name
            FROM league_matches lm
            JOIN bookings b ON lm.booking_id = b.id
            JOIN teams t1 ON lm.home_team_id = t1.id
            JOIN teams t2 ON lm.away_team_id = t2.id
            JOIN divisions d ON lm.division_id = d.id
            WHERE lm.division_id = %s
            ORDER BY b.date DESC, b.time DESC
        """, (division_id,))
    else:
        cur.execute("""
            SELECT lm.id, b.date, b.time, t1.name, t2.name, lm.home_score, lm.away_score, lm.referee, lm.status, d.name
            FROM league_matches lm
            JOIN bookings b ON lm.booking_id = b.id
            JOIN teams t1 ON lm.home_team_id = t1.id
            JOIN teams t2 ON lm.away_team_id = t2.id
            JOIN divisions d ON lm.division_id = d.id
            ORDER BY b.date DESC, b.time DESC
        """)
    matches = cur.fetchall()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT id, name, phone, court, time, date, booking_type, amount, paid, duration
        FROM bookings 
        WHERE date = %s AND booking_type != 'league'
        ORDER BY time
    """, (date_str,))
    other_bookings = cur.fetchall()
    cur.execute("""
        SELECT lm.id, b.time, t1.name, t2.name, lm.referee, b.amount, lm.paid_amount, lm.payment_status, b.id as booking_id
        FROM league_matches lm
        JOIN bookings b ON lm.booking_id = b.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE b.date = %s
        ORDER BY b.time
    """, (date_str,))
    league_matches = cur.fetchall()
    cur.execute("""
        SELECT p.booking_id, p.payer_name, p.amount, p.method, p.date
        FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE b.date = %s AND b.booking_type = 'social'
        ORDER BY p.created_at
    """, (date_str,))
    social_payments = cur.fetchall()
    cur.execute("""
        SELECT lp.booking_id, lp.player_name, t.name as team_name, lp.amount, lp.method, lp.date
        FROM league_payments lp
        JOIN bookings b ON lp.booking_id = b.id
        JOIN teams t ON lp.team_id = t.id
        WHERE b.date = %s
        ORDER BY lp.created_at
    """, (date_str,))
    league_payments = cur.fetchall()
    cur.execute("""
        SELECT id, supplier, invoice_no, amount, reason, created_at
        FROM expenses
        WHERE date = %s
        ORDER BY created_at
    """, (date_str,))
    expenses = cur.fetchall()
    cur.execute("""
        SELECT s.name, sd.shift
        FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = %s
        ORDER BY sd.shift
    """, (date_str,))
    staff_on_duty = cur.fetchall()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT amount, paid FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()
    if booking:
        amount_to_pay = booking[0] - booking[1]
        if amount_to_pay > 0:
            cur.execute("""
                INSERT INTO payments (booking_id, payer_name, amount, method, date)
                VALUES (%s, 'System Complete', %s, 'cash', CURRENT_DATE)
            """, (booking_id, amount_to_pay))
            cur.execute("UPDATE bookings SET paid = amount WHERE id = %s", (booking_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("daily_report", date=date_str))

@app.route("/api/mark-league-complete/<int:match_id>", methods=["POST"])
def mark_league_complete(match_id):
    if "user" not in session:
        return redirect(url_for("login"))
    date_str = request.form.get("date")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE league_matches SET payment_status = 'paid' WHERE id = %s", (match_id,))
    cur.execute("SELECT booking_id FROM league_matches WHERE id = %s", (match_id,))
    booking_id = cur.fetchone()
    if booking_id:
        cur.execute("SELECT amount FROM bookings WHERE id = %s", (booking_id[0],))
        amount = cur.fetchone()
        if amount:
            cur.execute("UPDATE league_matches SET paid_amount = %s WHERE id = %s", (amount[0], match_id))
    conn.commit()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, name, phone, created_at FROM staff ORDER BY name")
    all_staff = cur.fetchall()
    cur.execute("""
        SELECT sd.id, s.name, sd.shift FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date = %s
        ORDER BY sd.shift
    """, (date_str,))
    staff_on_duty = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("staff.html", staff=all_staff, staff_on_duty=staff_on_duty, date=date_str, user=session.get("user"))

@app.route("/staff/reports")
def staff_reports():
    if "user" not in session:
        return redirect(url_for("login"))
    from_date = request.args.get("from_date", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date = request.args.get("to_date", datetime.now().strftime("%Y-%m-%d"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT s.id, s.name, 
               COUNT(DISTINCT sd.date) as total_days,
               COUNT(sd.id) as total_shifts,
               STRING_AGG(DISTINCT sd.shift, ',') as shifts_types
        FROM staff s
        LEFT JOIN staff_duty sd ON s.id = sd.staff_id AND sd.date BETWEEN %s AND %s
        GROUP BY s.id
        ORDER BY total_shifts DESC
    """, (from_date, to_date))
    staff_summary = cur.fetchall()
    cur.execute("""
        SELECT s.name, sd.date, sd.shift
        FROM staff_duty sd
        JOIN staff s ON sd.staff_id = s.id
        WHERE sd.date BETWEEN %s AND %s
        ORDER BY sd.date DESC, s.name
    """, (from_date, to_date))
    staff_shifts = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("staff_reports.html", staff_summary=staff_summary, staff_shifts=staff_shifts, from_date=from_date, to_date=to_date, user=session.get("user"))

@app.route("/api/staff/add", methods=["POST"])
def add_staff():
    if "user" not in session:
        return redirect(url_for("login"))
    name = request.form["name"]
    phone = request.form.get("phone", "")
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute("INSERT INTO staff (name, phone) VALUES (%s, %s)", (name, phone))
        conn.commit()
    except psycopg2.IntegrityError:
        conn.rollback()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO staff_duty (date, staff_id, shift) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING", (date_str, staff_id, shift))
    cur.execute("INSERT INTO staff_shift_records (staff_id, date, shift, hours_worked) VALUES (%s, %s, %s, %s) ON CONFLICT (staff_id, date, shift) DO UPDATE SET hours_worked = EXCLUDED.hours_worked", (staff_id, date_str, shift, hours))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("staff", date=date_str))

@app.route("/api/staff/duty/remove/<int:duty_id>", methods=["POST"])
def remove_staff_duty(duty_id):
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT date, staff_id, shift FROM staff_duty WHERE id = %s", (duty_id,))
    duty = cur.fetchone()
    if duty:
        cur.execute("DELETE FROM staff_duty WHERE id = %s", (duty_id,))
        cur.execute("DELETE FROM staff_shift_records WHERE staff_id = %s AND date = %s AND shift = %s", (duty[1], duty[0], duty[2]))
        conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("staff", date=duty[0] if duty else None))

# -----------------------------
# REFEREE REPORTS
# -----------------------------
@app.route("/referee/reports")
def referee_reports():
    if "user" not in session:
        return redirect(url_for("login"))
    from_date = request.args.get("from_date", (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"))
    to_date = request.args.get("to_date", datetime.now().strftime("%Y-%m-%d"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT referee_name, COUNT(*) as total_games, SUM(fee) as total_fees, SUM(paid) as total_paid, (SUM(fee) - SUM(paid)) as balance
        FROM referee_records
        WHERE date BETWEEN %s AND %s
        GROUP BY referee_name
        ORDER BY total_games DESC
    """, (from_date, to_date))
    referee_summary = cur.fetchall()
    cur.execute("""
        SELECT rr.id, rr.referee_name, rr.date, t1.name as home_team, t2.name as away_team, rr.fee, rr.paid
        FROM referee_records rr
        JOIN league_matches lm ON rr.match_id = lm.id
        JOIN teams t1 ON lm.home_team_id = t1.id
        JOIN teams t2 ON lm.away_team_id = t2.id
        WHERE rr.date BETWEEN %s AND %s
        ORDER BY rr.date DESC, rr.referee_name
    """, (from_date, to_date))
    referee_games = cur.fetchall()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE referee_records SET fee = %s WHERE id = %s", (fee, record_id))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("referee_reports", from_date=from_date, to_date=to_date))

@app.route("/api/referee/mark_paid", methods=["POST"])
def mark_referee_paid():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    record_id = request.form["record_id"]
    from_date = request.form.get("from_date")
    to_date = request.form.get("to_date")
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE referee_records SET paid = fee WHERE id = %s", (record_id,))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("referee_reports", from_date=from_date, to_date=to_date))

# -----------------------------
# CASH MANAGEMENT
# -----------------------------
def get_cash_summary(date_str):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT start_cash, counted_cash FROM cash_days WHERE date = %s", (date_str,))
    cash_day = cur.fetchone()
    start_cash = cash_day[0] if cash_day else 0
    counted_cash = cash_day[1] if cash_day else 0
    cur.execute("""
        SELECT COALESCE(SUM(p.amount),0) FROM payments p
        JOIN bookings b ON p.booking_id = b.id
        WHERE p.method = 'cash' AND p.date = %s AND b.booking_type = 'social'
    """, (date_str,))
    social_cash = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(amount),0) FROM league_payments WHERE method = 'cash' AND date = %s", (date_str,))
    league_cash = cur.fetchone()[0]
    total_cash_income = social_cash + league_cash
    cur.execute("SELECT id, supplier, invoice_no, amount, reason, created_at FROM expenses WHERE date = %s ORDER BY created_at", (date_str,))
    expenses = cur.fetchall()
    total_expenses = sum(e[3] for e in expenses) if expenses else 0
    expected_cash = start_cash + total_cash_income - total_expenses
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO cash_days (date, start_cash) VALUES (%s, %s) ON CONFLICT (date) DO UPDATE SET start_cash = EXCLUDED.start_cash", (date_str, start_cash))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("cash_page", date=date_str))

@app.route("/api/cash/count", methods=["POST"])
def record_cash_count():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    date_str = request.form["date"]
    counted_cash = int(request.form["counted_cash"])
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE cash_days SET counted_cash = %s, counted_at = CURRENT_TIMESTAMP WHERE date = %s", (counted_cash, date_str))
    if cur.rowcount == 0:
        cur.execute("INSERT INTO cash_days (date, counted_cash, counted_at) VALUES (%s, %s, CURRENT_TIMESTAMP)", (date_str, counted_cash))
    conn.commit()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("INSERT INTO expenses (date, supplier, invoice_no, amount, reason) VALUES (%s, %s, %s, %s, %s)", (date_str, supplier, invoice_no, amount, reason))
    conn.commit()
    cur.close()
    conn.close()
    return redirect(url_for("cash_page", date=date_str))

@app.route("/api/expenses/delete/<int:expense_id>", methods=["POST"])
def delete_expense(expense_id):
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT date FROM expenses WHERE id = %s", (expense_id,))
    exp = cur.fetchone()
    if exp:
        cur.execute("DELETE FROM expenses WHERE id = %s", (expense_id,))
        conn.commit()
        cur.close()
        conn.close()
        return redirect(url_for("cash_page", date=exp[0]))
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cur.execute("SELECT date, SUM(amount) FROM payments WHERE date >= %s GROUP BY date ORDER BY date", (thirty_days_ago,))
    daily_revenue = cur.fetchall()
    cur.execute("SELECT TO_CHAR(date, 'YYYY-WW') as week, SUM(amount) FROM payments GROUP BY week ORDER BY week DESC LIMIT 12")
    weekly_revenue = cur.fetchall()
    cur.execute("SELECT method, SUM(amount) FROM payments GROUP BY method")
    method_breakdown = cur.fetchall()
    cur.close()
    conn.close()
    return render_template("analytics.html", daily_revenue=daily_revenue, weekly_revenue=weekly_revenue, method_breakdown=method_breakdown, user=session.get("user"))

@app.route("/export/bookings")
def export_bookings():
    if "user" not in session:
        return redirect(url_for("login"))
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT * FROM bookings ORDER BY date DESC, time")
    bookings = cur.fetchall()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT name, phone, court, time, date FROM bookings WHERE id = %s", (booking_id,))
    booking = cur.fetchone()
    cur.close()
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
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        SELECT TO_CHAR(date, 'YYYY-MM') as month, COUNT(*) as count, SUM(amount) as total, SUM(paid) as paid
        FROM bookings
        GROUP BY month
        ORDER BY month DESC
    """)
    rows = cur.fetchall()
    cur.close()
    conn.close()
    result = [{"month": r[0], "count": r[1], "total": r[2], "paid": r[3]} for r in rows]
    return jsonify(result)

@app.route("/api/analytics-data")
def analytics_data():
    if "user" not in session:
        return jsonify({"error": "Unauthorized"}), 401
    conn = get_db_connection()
    cur = conn.cursor()
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
    cur.execute("SELECT date, SUM(amount) FROM payments WHERE date >= %s GROUP BY date ORDER BY date", (thirty_days_ago,))
    daily_revenue = cur.fetchall()
    cur.execute("SELECT TO_CHAR(date, 'YYYY-WW') as week, SUM(amount) FROM payments GROUP BY week ORDER BY week DESC LIMIT 12")
    weekly_revenue = cur.fetchall()
    cur.execute("SELECT method, SUM(amount) FROM payments GROUP BY method")
    method_breakdown = cur.fetchall()
    cur.close()
    conn.close()
    return jsonify({
        "daily": [{"date": d[0], "revenue": d[1]} for d in daily_revenue],
        "weekly": [{"week": w[0], "revenue": w[1]} for w in weekly_revenue],
        "methods": [{"method": m[0], "total": m[1]} for m in method_breakdown]
    })

# -----------------------------
# TEST ROUTES
# -----------------------------
@app.route("/checkdb")
def checkdb():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM bookings")
        count = cur.fetchone()[0]
        cur.close()
        conn.close()
        return f"Database connected. Bookings count: {count}"
    except Exception as e:
        return f"Error: {e}"

@app.route("/debug")
def debug():
    import os
    url = os.environ.get('DATABASE_URL', 'NOT SET')
    # Hide password for safety
    if url and '@' in url:
        parts = url.split('@')
        user_pass = parts[0].split('://')[1]
        masked = url.replace(user_pass, '***')
    else:
        masked = url
    return f"DATABASE_URL: {masked}"

# -----------------------------
# RUN
# -----------------------------
if __name__ == "__main__":
    app.run(debug=True)