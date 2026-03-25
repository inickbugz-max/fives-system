from flask import Flask, render_template, request, redirect
import sqlite3

app = Flask(__name__)

# DATABASE
def get_db():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    return conn


# HOME
@app.route('/')
def home():
    return render_template('dashboard.html')


# MONTHLY (WITH COURTS)
@app.route('/monthly', methods=['GET', 'POST'])
def monthly():
    conn = get_db()
    cursor = conn.cursor()

    # CREATE TABLE WITH COURT COLUMN
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS bookings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            date TEXT,
            time TEXT,
            court INTEGER
        )
    ''')

    message = ""

    if request.method == 'POST':
        name = request.form.get('name')
        date = request.form.get('date')
        time = request.form.get('time')

        # GET EXISTING BOOKINGS FOR SLOT
        cursor.execute(
            "SELECT court FROM bookings WHERE date = ? AND time = ?",
            (date, time)
        )
        existing = cursor.fetchall()

        used_courts = [row["court"] for row in existing]

        # FIND AVAILABLE COURT
        for court in [1, 2, 3]:
            if court not in used_courts:
                assigned_court = court
                break
        else:
            assigned_court = None

        if assigned_court is None:
            message = "❌ All courts are booked!"
        else:
            cursor.execute(
                "INSERT INTO bookings (name, date, time, court) VALUES (?, ?, ?, ?)",
                (name, date, time, assigned_court)
            )
            conn.commit()
            message = f"✅ Booked on Court {assigned_court}"

    # GET BOOKINGS
    cursor.execute("SELECT * FROM bookings ORDER BY date, time, court")
    bookings = cursor.fetchall()

    conn.close()

    return render_template('monthly.html', bookings=bookings, message=message)


# DELETE
@app.route('/delete/<int:id>')
def delete(id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM bookings WHERE id = ?", (id,))
    conn.commit()
    conn.close()

    return redirect('/monthly')


# OTHER PAGES
@app.route('/daily')
def daily():
    return render_template('daily.html')

@app.route('/billing')
def billing():
    return render_template('billing.html')

@app.route('/calendar')
def calendar():
    return render_template('calendar.html')

@app.route('/league')
def league():
    return render_template('league.html')

@app.route('/games')
def games():
    return render_template('games.html')

@app.route('/fixtures')
def fixtures():
    return render_template('fixtures.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/ref-stats')
def ref_stats():
    return render_template('ref_stats.html')


# RUN
if __name__ == "__main__":
    app.run(debug=True)