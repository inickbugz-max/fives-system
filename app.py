from flask import Flask, render_template, request

app = Flask(__name__)

# 🔥 TEMP STORAGE (for bookings)
bookings = []


# 🏠 HOME (DASHBOARD)
@app.route('/')
def home():
    return render_template('dashboard.html')


# 📊 MONTHLY (BOOKING SYSTEM)
@app.route('/monthly', methods=['GET', 'POST'])
def monthly():
    if request.method == 'POST':
        name = request.form.get('name')
        date = request.form.get('date')
        time = request.form.get('time')

        bookings.append({
            "name": name,
            "date": date,
            "time": time
        })

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


# 🧑‍⚖️ REF STATS (FIXED — NO ERROR)
@app.route('/ref-stats')
def ref_stats():
    return render_template('ref_stats.html')


# ▶ RUN LOCAL (Render uses gunicorn)
if __name__ == "__main__":
    app.run(debug=True)