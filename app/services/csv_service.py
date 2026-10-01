import csv
import io
import re
from app.extensions import db
from app.models import Player, PlayerRole, PlayerCategory, PlayerStatus
from app.models.audit import AuditLog

# Canonical field mapping with common header variations
HEADER_ALIASES = {
    'rule_number': ['rule number', 'rule no', 'rule_no', 'ruleno', 'rule_number', 'roll number', 'roll no', 'roll_no', 'rollno', 'roll_number'],
    'name': ['name', 'player name', 'player_name', 'full name', 'fullname'],
    'photo': ['photo', 'photo url', 'photo_url', 'image', 'image_url', 'picture'],
    'role': ['role', 'player role', 'player_role', 'playing role'],
    'branch': ['branch', 'department', 'dept'],
    'year': ['year', 'current year', 'batch'],
    'experience': ['experience', 'matches', 'stats', 'level', 'player experience'],
    'category': ['category', 'player category', 'tier', 'grade'],
    'base_price': ['base price', 'base_price', 'baseprice', 'price', 'base']
}

def map_headers(raw_headers):
    """Map raw CSV headers to canonical field names."""
    mapping = {}
    for raw in raw_headers:
        if not raw:
            continue
        cleaned = re.sub(r'[_\s]+', ' ', raw.strip().lower())
        for canonical, aliases in HEADER_ALIASES.items():
            if cleaned in aliases or raw.strip().lower() == canonical:
                mapping[raw] = canonical
                break
    return mapping

def preview_players_csv(csv_content):
    """
    Parse and validate CSV content without saving to database.
    Returns preview analysis, detected duplicates, and row-by-row status.
    """
    result = {
        'total': 0,
        'valid_count': 0,
        'duplicate_count': 0,
        'error_count': 0,
        'preview_rows': [],
        'errors': [],
        'headers_found': []
    }

    if isinstance(csv_content, bytes):
        csv_content = csv_content.decode('utf-8-sig', errors='replace')

    stream = io.StringIO(csv_content)
    reader = csv.DictReader(stream)

    if not reader.fieldnames:
        result['errors'].append('CSV file is empty or unreadable.')
        return result

    header_map = map_headers(reader.fieldnames)
    result['headers_found'] = list(header_map.values())

    if 'rule_number' not in header_map.values() or 'name' not in header_map.values():
        result['errors'].append("Missing essential columns: 'Rule Number' and 'Name' must be present.")
        return result

    existing_rule_numbers = {p.roll_number.strip().lower() for p in Player.query.all()}
    batch_rule_numbers = set()

    row_index = 0
    for raw_row in reader:
        row_index += 1
        canonical_row = {}
        for raw_k, val in raw_row.items():
            if raw_k in header_map:
                canonical_row[header_map[raw_k]] = (val.strip() if val else '')

        rule_no = canonical_row.get('rule_number', '').strip()
        name = canonical_row.get('name', '').strip()
        photo = canonical_row.get('photo', '').strip()
        role = canonical_row.get('role', 'BATSMAN').strip().upper()
        branch = canonical_row.get('branch', '').strip()
        year = canonical_row.get('year', '').strip()
        exp = canonical_row.get('experience', '').strip()
        cat = canonical_row.get('category', 'NORMAL').strip().upper()
        price_str = canonical_row.get('base_price', '10000').strip()

        row_status = 'VALID'
        status_msg = 'Ready to import'

        if not rule_no or not name:
            row_status = 'ERROR'
            status_msg = 'Missing Rule Number or Name'
            result['error_count'] += 1
        elif role not in PlayerRole.CHOICES:
            row_status = 'ERROR'
            status_msg = f"Invalid role '{role}'. Allowed: {', '.join(PlayerRole.CHOICES)}"
            result['error_count'] += 1
        elif cat not in PlayerCategory.CHOICES:
            row_status = 'ERROR'
            status_msg = f"Invalid category '{cat}'. Allowed: {', '.join(PlayerCategory.CHOICES)}"
            result['error_count'] += 1
        elif rule_no.lower() in batch_rule_numbers:
            row_status = 'DUPLICATE'
            status_msg = f"Duplicate rule number '{rule_no}' in this CSV"
            result['duplicate_count'] += 1
        elif rule_no.lower() in existing_rule_numbers:
            row_status = 'DUPLICATE'
            status_msg = f"Rule number '{rule_no}' already exists in database"
            result['duplicate_count'] += 1
        else:
            try:
                price = float(price_str)
                if price < 0:
                    price = 10000.0
            except ValueError:
                price = 10000.0

            result['valid_count'] += 1
            batch_rule_numbers.add(rule_no.lower())

        result['preview_rows'].append({
            'row_num': row_index,
            'rule_number': rule_no,
            'name': name,
            'photo': photo or 'default_player.png',
            'role': role,
            'branch': branch,
            'year': year,
            'experience': exp,
            'category': cat,
            'base_price': price_str,
            'status': row_status,
            'message': status_msg
        })

    result['total'] = row_index
    return result

def parse_and_import_players_csv(csv_content):
    """
    Parses and imports players from CSV.
    Skips invalid rows and duplicates, inserts valid players into JSON store.
    """
    preview = preview_players_csv(csv_content)
    result = {
        'imported': 0,
        'skipped': 0,
        'duplicates': preview['duplicate_count'],
        'errors': []
    }

    if preview['errors']:
        result['errors'] = [{'row': 0, 'message': err} for err in preview['errors']]
        return result

    players_to_add = []
    for r in preview['preview_rows']:
        if r['status'] == 'VALID':
            try:
                base_price = float(r['base_price'])
            except ValueError:
                base_price = 10000.0

            player = Player(
                roll_number=r['rule_number'],
                name=r['name'],
                photo=r['photo'] or 'default_player.png',
                role=r['role'] if r['role'] in PlayerRole.CHOICES else PlayerRole.BATSMAN,
                branch=r['branch'],
                year=r['year'],
                experience=r['experience'],
                category=r['category'] if r['category'] in PlayerCategory.CHOICES else PlayerCategory.NORMAL,
                base_price=base_price,
                status=PlayerStatus.AVAILABLE,
                auction_type='PRIMARY'
            )
            players_to_add.append(player)
        else:
            result['skipped'] += 1
            result['errors'].append({'row': r['row_num'], 'message': f"{r['rule_number']} - {r['name']}: {r['message']}"})

    if players_to_add:
        try:
            db.session.add_all(players_to_add)
            db.session.commit()
            result['imported'] = len(players_to_add)
        except Exception as e:
            db.session.rollback()
            result['errors'].append({'row': 0, 'message': f"Storage error: {str(e)}"})

    return result
