import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATA_DIR = os.path.join(BASE_DIR, 'data')
UPLOAD_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'webp', 'svg', 'xlsx', 'xls', 'csv'}

SECRET_KEY = os.environ.get('SECRET_KEY', 'kspl-auction-secret-key-2026')
DEBUG = True

# JSON storage file paths
TEAMS_FILE = os.path.join(DATA_DIR, 'teams.json')
PLAYERS_FILE = os.path.join(DATA_DIR, 'players.json')
AUCTION_FILE = os.path.join(DATA_DIR, 'auction.json')
BIDS_FILE = os.path.join(DATA_DIR, 'bids.json')
SETTINGS_FILE = os.path.join(DATA_DIR, 'settings.json')
AUDIT_FILE = os.path.join(DATA_DIR, 'audit_log.json')
STUDENTS_FILE = os.path.join(DATA_DIR, 'students.json')

# Core SPL Constants
DEFAULT_PURSE = 500000  # ₹5,00,000 per franchise
MAX_SQUAD_SIZE = 15     # 15 players max per franchise
DEFAULT_BASE_PRICE = 10000
DEFAULT_TIMER_SECONDS = 30

# Student Registration Constants
MAX_PHOTO_SIZE_BYTES = 100 * 1024  # 100 KB maximum photo size
DOB_FORMAT = 'DDMMYYYY'
STUDENT_YEARS = ['1st Year', '2nd Year', '3rd Year', '4th Year']
STUDENT_DEPARTMENTS = [
    'CSE',
    'CSE - Cyber Security',
    'CSE - AI & ML',
    'CSE - Data Science',
    'ECE',
    'EEE',
    'MECH',
    'CIVIL',
    'IT'
]
STUDENT_PLAYING_ROLES = ['Batsman', 'Bowler', 'All-Rounder']


# System role accounts (Admin & Anchor)
# Team accounts are dynamically managed in teams.json with authorized Gmails
ROLES = {
    'admin': {
        'username': 'admin',
        'password': 'admin123',
        'email': 'admin@spl.edu',
        'role': 'admin',
        'title': 'SPL Auction Administrator'
    },
    'anchor': {
        'username': 'anchor',
        'password': 'anchor123',
        'email': 'anchor@spl.edu',
        'role': 'anchor',
        'title': 'SPL Anchor / Auctioneer'
    }
}


