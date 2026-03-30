# Fives System – Court Booking & League Management

A comprehensive Flask-based web application for managing court bookings, league games, payments, staff, and daily reports.

## Features

- **3 Courts** with hourly slots (6:00 AM – 11:00 PM)
- **Multiple Booking Types**: Social, League, Birthday Party, Event, Soccer School, Open Social
- **Duration Booking**: Book 1‑4 hours – system reserves consecutive slots
- **Payment Tracking**: Cash, Card, EFT – separate for social and league
- **League Management**: Multiple divisions (Monday–Sunday), teams, standings, scores, referee tracking
- **Team Payments**: Record payments by player, track total paid and balance
- **Staff Management**: Assign staff to shifts, generate shift reports
- **Daily Reports**: View all bookings, payments, expenses, cash count – with print option
- **WhatsApp Reminders**: One‑click reminder for any booking
- **Analytics**: Daily/weekly revenue charts, payment method breakdown
- **Cash Management**: Record start cash, expenses, end‑of‑day cash count with note/coin breakdown
- **Professional UI**: Bootstrap 5, responsive, color‑coded booking cells

## Technology Stack

- **Backend**: Flask (Python)
- **Database**: SQLite
- **Frontend**: Bootstrap 5, Chart.js
- **Deployment**: PythonAnywhere / Render (supports SQLite)

## Installation (Local)

1. **Clone the repository**
   ```bash
   git clone https://github.com/yourusername/fives-system.git
   cd fives-system