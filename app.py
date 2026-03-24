from flask import Flask, render_template

app = Flask(__name__)

# 🏠 HOME (DASHBOARD)
@app.route('/')
def home():
    return render_template('dashboard.html')


# 📊 CORE PAGES
@app.route('/monthly')
def monthly():
    return render_template('monthly.html')

@app.route('/daily')
def daily():
    return render_template('daily.html')

@app.route('/billing')
def billing():
    return render_template('billing.html')

@app.route('/calendar')
def calendar():
    return render_template('calendar.html')


# ⚽ EXTRA PAGES
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


# ▶ RUN LOCAL
if __name__ == "__main__":
    app.run(debug=True)