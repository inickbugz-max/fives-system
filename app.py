from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('monthly.html')

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

@app.route('/receipt')
def receipt():
    return render_template('receipt.html')

@app.route('/dashboard')
def dashboard():
    return render_template('dashboard.html')

@app.route('/login')
def login():
    return render_template('login.html')

@app.route('/league')
def league():
    return render_template('league.html')

@app.route('/games')
def games():
    return render_template('games.html')

@app.route('/fixtures')
def fixtures():
    return render_template('fixtures.html')

@app.route('/player')
def player():
    return render_template('player.html')

@app.route('/reports')
def reports():
    return render_template('reports.html')

@app.route('/team-stats')
def team_stats():
    return render_template('team_stats.html')

@app.route('/ref-stats')
def ref_stats():
    return render_template('ref_stats.html')

@app.route('/ref-report')
def ref_report():
    return render_template('ref_report.html')

@app.route('/refs')
def refs():
    return render_template('refs.html')


# Required for local run (Render uses gunicorn)
if __name__ == "__main__":
    app.run(debug=True)
