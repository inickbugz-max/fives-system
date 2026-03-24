from flask import Flask, render_template, request
import sqlite3

app = Flask(__name__)

# 🔌 CONNECT TO DATABASE
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn


# 🏠 HOME
@app.route('/')
def home():
    return render_template('dashboard.html')


# 📊 MONTHLY (REAL BOOKING SYSTEM)
@app.route('/monthly', methods=['GET', 'POST'])
def monthly():
    conn = get_db()
    cursor = conn.cursor()

    # CREATE TABLE IF NOT EXISTS
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            time TEXT
        )
    ''')

    # ADD BOOKING
    if request.method == 'POST':
        name = request.form.get('name')
        date = request.form.get('date')
        time = request.form.get('time')

        cursor.execute(
            "INSERT INTO bookings (name, date, time) VALUES (?, ?, ?)",
            (name, date, time)
        )
        conn.commit()

    # GET BOOKINGS
    cursor.execute("SELECT * FROM bookings ORDER BY date, time")
    bookings = cursor.fetchall()

    conn.close()

    return render_template('monthly.html', bookings=bookings)


# 📅 DAILY
@app.route('/daily')
def daily():
    return render_template('daily.html')


# 💰 BILLING
@app.route('/billing')
def billing():
    return render_template('billing.html')


# 🗓 CALENDAR
@app.route('/calendar')
def calendar():
    return render_template('calendar.html')


# ⚽ LEAGUE
@app.route('/league')
def league():
    return render_template('league.html')


# 🎮 GAMES
@app.route('/games')
def games():
    return render_template('games.html')


# 📋 FIXTURES
@app.route('/fixtures')
def fixtures():
    return render_template('fixtures.html')


# 📊 REPORTS
@app.route('/reports')
def reports():
    return render_template('reports.html')


# 🧑‍⚖️ REF STATS
@app.route('/ref-stats')
def ref_stats():
    return render_template('ref_stats.html')


# ▶ RUN
if __name__ == "__main__":
    app.run(debug=True)