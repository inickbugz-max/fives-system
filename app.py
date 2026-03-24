from flask import Flask, render_template, request, redirect, session, send_file
import sqlite3
from datetime import datetime
import pandas as pd

app = Flask(__name__)
app.secret_key = "secret123"

OWNER_NUMBER = "270685106617"

# =========================
# DATABASE
# =========================
def init_db():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    c.execute("""
    CREATE TABLE IF NOT EXISTS bookings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT,
        phone TEXT,
        time TEXT,
        court TEXT,
        amount INTEGER,
        paid INTEGER DEFAULT 0,
        date TEXT
    )
    """)

    c.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        team1 TEXT,
        team2 TEXT,
        score1 INTEGER,
        score2 INTEGER,
        referee TEXT,
        date TEXT
    )
    """)

    conn.commit()
    conn.close()

init_db()

# =========================
# LOGIN
# =========================
@app.route("/", methods=["GET","POST"])
def login():
    if request.method == "POST":
        session["user"] = request.form["username"]
        return redirect("/dashboard")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect("/")

# =========================
# DASHBOARD
# =========================
@app.route("/dashboard")
def dashboard():
    if "user" not in session:
        return redirect("/")

    times = ["18:00","19:00","20:00","21:00"]
    courts = ["Court 2 (5s)", "Court 3 (5s)", "Court 4 (7s)"]

    return render_template("dashboard.html", times=times, courts=courts)

# =========================
# ADD BOOKING
# =========================
@app.route("/add", methods=["POST"])
def add_booking():
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    today = datetime.now().strftime("%Y-%m-%d")

    c.execute("""
    INSERT INTO bookings (name, phone, time, court, amount, date)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        request.form["name"],
        request.form["phone"],
        request.form["time"],
        request.form["court"],
        request.form["amount"],
        today
    ))

    conn.commit()
    conn.close()

    return redirect("/dashboard")

# =========================
# MONTHLY DATA FUNCTION
# =========================
def get_monthly_data(selected_month=None):
    conn = sqlite3.connect("database.db")
    c = conn.cursor()

    bookings = c.execute("SELECT * FROM bookings").fetchall()
    conn.close()

    players = {}
    total_collected = 0
    total_outstanding = 0

    for b in bookings:
        name = b[1]
        amount = int(b[5])
        paid = int(b[6])
        date = b[7]

        if selected_month and not date.startswith(selected_month):
            continue

        if name not in players:
            players[name] = {"total": 0, "paid": 0}

        players[name]["total"] += amount
        players[name]["paid"] += paid

        total_collected += paid
        total_outstanding += (amount - paid)

    return players, total_collected, total_outstanding

# =========================
# MONTHLY PAGE
# =========================
@app.route("/monthly")
def monthly():
    if "user" not in session:
        return redirect("/")

    selected_month = request.args.get("month")

    players, total_collected, total_outstanding = get_monthly_data(selected_month)

    return render_template(
        "monthly.html",
        players=players,
        total_collected=total_collected,
        total_outstanding=total_outstanding,
        selected_month=selected_month
    )

# =========================
# 📄 PREMIUM PDF EXPORT
# =========================
@app.route("/export_pdf")
def export_pdf():
    month = request.args.get("month")

    players, total_collected, total_outstanding = get_monthly_data(month)

    file_path = "monthly_report.pdf"

    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet

    doc = SimpleDocTemplate(file_path)
    styles = getSampleStyleSheet()
    content = []

    # HEADER
    content.append(Paragraph("FIVES FUTBOL", styles["Title"]))
    content.append(Spacer(1, 10))
    content.append(Paragraph("Monthly Financial Report", styles["Heading2"]))
    content.append(Spacer(1, 10))

    if month:
        content.append(Paragraph(f"Month: {month}", styles["Normal"]))
        content.append(Spacer(1, 10))

    # TABLE
    table_data = [["Player", "Paid (R)", "Total (R)"]]

    for name, data in players.items():
        table_data.append([
            name,
            str(data["paid"]),
            str(data["total"])
        ])

    table = Table(table_data)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (1, 1), (-1, -1), "CENTER"),
    ]))

    content.append(table)
    content.append(Spacer(1, 20))

    # TOTALS
    content.append(Paragraph(f"Total Collected: R{total_collected}", styles["Normal"]))
    content.append(Paragraph(f"Total Outstanding: R{total_outstanding}", styles["Normal"]))

    content.append(Spacer(1, 20))
    content.append(Paragraph("Thank you for your support ⚽", styles["Italic"]))

    doc.build(content)

    return send_file(file_path, as_attachment=True)

# =========================
# 📊 EXPORT EXCEL
# =========================
@app.route("/export_excel")
def export_excel():
    month = request.args.get("month")

    players, _, _ = get_monthly_data(month)

    data = []
    for name, d in players.items():
        data.append({
            "Player": name,
            "Paid": d["paid"],
            "Total": d["total"]
        })

    df = pd.DataFrame(data)

    file_path = "monthly_report.xlsx"
    df.to_excel(file_path, index=False)

    return send_file(file_path, as_attachment=True)

# =========================
# RUN
# =========================
if __name__ == "__main__":
    app.run(debug=True)