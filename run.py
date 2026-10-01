import os
from app import create_app
from app.extensions import db
from app.services.seed_service import seed_database
from app.services.db_sync_service import sync_database_schema

app = create_app(os.environ.get('FLASK_ENV', 'dev'))

@app.cli.command('init-db')
def init_db_command():
    """Clear existing data and create new JSON storage with initial seed data."""
    db.create_all()
    sync_database_schema()
    seed_database()
    print("JSON storage initialized and seeded successfully.")

with app.app_context():
    # Ensure tables, columns, and seed data exist on startup
    db.create_all()
    sync_database_schema()
    seed_database()

if __name__ == '__main__':
    requested_port = int(os.environ.get('PORT', 5000))

    if os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        import socket

        def is_port_in_use(p):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                return s.connect_ex(('127.0.0.1', p)) == 0

        port = requested_port
        while is_port_in_use(port):
            if port == 5000:
                print(f"[INFO] Port {port} is in use (often macOS AirPlay Receiver). Trying port {port + 1}...")
            else:
                print(f"[INFO] Port {port} is in use. Trying port {port + 1}...")
            port += 1
            if port > requested_port + 20:
                break
        os.environ['PORT'] = str(port)
    else:
        port = requested_port

    print(f"[INFO] Starting SPL Auction System on http://127.0.0.1:{port}/")
    app.run(host='127.0.0.1', port=port, debug=True)

